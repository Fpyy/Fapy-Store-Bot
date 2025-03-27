import discord
from discord import app_commands, ui, Embed, Interaction
from discord.ext import commands
import sqlite3
import random
import string
from datetime import datetime, timedelta
import asyncio

# Configurações
TOKEN = os.getenv('TOKEN')
CANAIS_LEILAO = [1354935337398436040, 1354935389584097440]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Banco de dados
conn = sqlite3.connect('leiloes.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS leiloes
             (message_id INTEGER PRIMARY KEY,
              canal_id INTEGER,
              dono_id INTEGER,
              nome_conta TEXT,
              preco_inicial REAL,
              maior_lance REAL,
              maior_lance_user INTEGER,
              data_fim TEXT)''')

conn.commit()

# Classe para gerenciar leilões ativos
class LeilaoManager:
    def __init__(self):
        self.leiloes_ativos = {}
        self.locks = {}

    async def iniciar_leilao(self, interaction, nome_conta, preco_inicial, duracao_horas):
        # Encontra um canal disponível
        canal_leilao = None
        for canal_id in CANAIS_LEILAO:
            c.execute("SELECT 1 FROM leiloes WHERE canal_id = ?", (canal_id,))
            if not c.fetchone():
                canal_leilao = bot.get_channel(canal_id)
                break

        if not canal_leilao:
            await interaction.followup.send("Todos os canais de leilão estão ocupados no momento.", ephemeral=True)
            return

        # Calcula data de término
        data_fim = datetime.now() + timedelta(hours=duracao_horas)
        
        # Cria embed do leilão
        embed = Embed(title=f"🎟️ LEILÃO: {nome_conta}", color=0xe67e22)
        embed.description = (
            "🏆 **Como participar?**\n"
            "1. Envie um valor numérico neste chat (ex: 10.50)\n"
            "2. Seu lance deve ser pelo menos R$ 0,50 maior que o atual\n"
            "3. O vencedor será quem oferecer o maior valor\n\n"
            "📢 **Regras:**\n"
            "• Diferença mínima entre lances: R$ 0,50\n"
            "• O vencedor terá 24h para pagar\n"
            "• Lances inválidos serão removidos"
        )
        embed.add_field(name="💰 Preço Inicial", value=f"R$ {preco_inicial:.2f}", inline=True)
        embed.add_field(name="⏳ Termina em", value=f"<t:{int(data_fim.timestamp())}:R>", inline=True)
        embed.add_field(name="🔢 Maior Lance", value=f"R$ {preco_inicial:.2f}", inline=True)
        embed.set_footer(text=f"Dono: {interaction.user.display_name}")

        # Envia mensagem do leilão
        msg = await canal_leilao.send("@everyone 🎉 **NOVO LEILÃO INICIADO!**", embed=embed)
        
        # Registra no banco de dados
        c.execute("INSERT INTO leiloes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (msg.id, canal_leilao.id, interaction.user.id, nome_conta,
                   preco_inicial, preco_inicial, None, data_fim.isoformat()))
        conn.commit()

        # Inicia monitoramento
        self.leiloes_ativos[msg.id] = {
            "message": msg,
            "channel": canal_leilao,
            "end_time": data_fim,
            "current_bid": preco_inicial,
            "current_winner": None
        }
        self.locks[msg.id] = asyncio.Lock()
        
        asyncio.create_task(self.monitorar_leilao(msg.id))

    async def monitorar_leilao(self, message_id):
        leilao = self.leiloes_ativos[message_id]
        
        while datetime.now() < leilao["end_time"]:
            try:
                await self.processar_lances(message_id)
            except Exception as e:
                print(f"Erro ao processar lances: {e}")
                await asyncio.sleep(5)
        
        await self.finalizar_leilao(message_id)

    async def processar_lances(self, message_id):
        leilao = self.leiloes_ativos[message_id]
        
        def check(m):
            return (m.channel.id == leilao["channel"].id and 
                    not m.author.bot and
                    not m.reference)  # Aceita mensagens sem reply
        
        try:
            msg = await bot.wait_for('message', check=check, timeout=60)
            async with self.locks[message_id]:
                await self.validar_lance(message_id, msg)
        except asyncio.TimeoutError:
            pass

    async def validar_lance(self, message_id, message):
        leilao = self.leiloes_ativos[message_id]
        
        try:
            valor = float(message.content.replace(',', '.'))
        except ValueError:
            await message.delete()
            await message.author.send("❌ Formato inválido! Envie apenas números (ex: 10 ou 10.50)")
            return

        # Verifica se o lance é válido
        if valor <= leilao["current_bid"]:
            await message.delete()
            await message.author.send(
                f"❌ Lance muito baixo! O lance atual é R$ {leilao['current_bid']:.2f}"
            )
            return

        if (valor - leilao["current_bid"]) < 0.5:
            await message.delete()
            await message.author.send(
                f"❌ Diferença mínima de R$0,50! Próximo lance mínimo: R$ {leilao['current_bid'] + 0.5:.2f}"
            )
            return

        # Atualiza lance
        leilao["current_bid"] = valor
        leilao["current_winner"] = message.author
        
        # Atualiza banco de dados
        c.execute("""
            UPDATE leiloes 
            SET maior_lance = ?, maior_lance_user = ? 
            WHERE message_id = ?
        """, (valor, message.author.id, message_id))
        conn.commit()
        
        # Atualiza embed
        embed = leilao["message"].embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "🔢 Maior Lance":
                embed.set_field_at(i, name="🔢 Maior Lance", 
                                 value=f"R$ {valor:.2f} por {message.author.mention}")
        
        await leilao["message"].edit(embed=embed)
        await message.add_reaction("✅")
        
        # Notificação temporária
        notification = await leilao["channel"].send(
            f"🎉 Novo lance! {message.author.mention} ofereceu R$ {valor:.2f}!",
            delete_after=10
        )

    async def finalizar_leilao(self, message_id):
        leilao = self.leiloes_ativos.pop(message_id, None)
        if not leilao:
            return
            
        # Atualiza embed
        embed = leilao["message"].embeds[0]
        embed.color = 0x2ecc71
        
        if leilao["current_winner"]:
            vencedor = leilao["current_winner"]
            valor = leilao["current_bid"]
            
            embed.add_field(
                name="🎉 Leilão Encerrado",
                value=f"**Vencedor:** {vencedor.mention} com R$ {valor:.2f}\n"
                      "🔹 Abra um ticket para finalizar a compra!",
                inline=False
            )
            
            try:
                await vencedor.send(
                    f"🎉 Você venceu o leilão de {embed.title}!\n"
                    f"Valor: R$ {valor:.2f}\n\n"
                    "Por favor, abra um ticket para finalizar a compra."
                )
            except:
                pass
        else:
            embed.add_field(
                name="ℹ️ Leilão Encerrado",
                value="Nenhum lance válido foi realizado.",
                inline=False
            )
        
        await leilao["message"].edit(content="🔔 LEILÃO ENCERRADO! @everyone", embed=embed)
        
        # Remove do banco de dados
        c.execute("DELETE FROM leiloes WHERE message_id = ?", (message_id,))
        conn.commit()

# Inicializa o manager
leilao_manager = LeilaoManager()

# Comandos
@bot.tree.command(name="criarleilao", description="Cria um novo leilão")
@app_commands.describe(
    nome_conta="Nome da conta sendo leiloada",
    preco_inicial="Preço inicial do leilão",
    duracao_horas="Duração do leilão em horas"
)
async def criar_leilao(interaction: Interaction, nome_conta: str, preco_inicial: float, duracao_horas: int):
    await interaction.response.defer(ephemeral=True)
    
    if duracao_horas < 1 or duracao_hours > 72:
        await interaction.followup.send("Duração deve ser entre 1 e 72 horas.", ephemeral=True)
        return
    
    await leilao_manager.iniciar_leilao(interaction, nome_conta, preco_inicial, duracao_horas)
    await interaction.followup.send("Leilão criado com sucesso!", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} está online!')
    
    # Recupera leilões ativos do banco de dados
    c.execute("SELECT * FROM leiloes")
    for leilao in c.fetchall():
        message_id, canal_id, _, nome_conta, preco_inicial, maior_lance, winner_id, data_fim = leilao
        
        try:
            channel = bot.get_channel(canal_id)
            message = await channel.fetch_message(message_id)
            data_fim = datetime.fromisoformat(data_fim)
            
            if datetime.now() < data_fim:
                # Recria leilão ativo
                leilao_manager.leiloes_ativos[message_id] = {
                    "message": message,
                    "channel": channel,
                    "end_time": data_fim,
                    "current_bid": maior_lance,
                    "current_winner": bot.get_user(winner_id) if winner_id else None
                }
                leilao_manager.locks[message_id] = asyncio.Lock()
                asyncio.create_task(leilao_manager.monitorar_leilao(message_id))
            else:
                # Finaliza leilão expirado
                asyncio.create_task(leilao_manager.finalizar_leilao(message_id))
        except:
            continue

bot.run(TOKEN)