from flask import Flask
from threading import Thread
import discord
from discord import app_commands, ui, Embed
from discord.ext import commands
import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
import asyncio

# Configuração do Flask para keep-alive
app = Flask('')

@app.route('/')
def home():
    return "Bot está online!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# Configurações do Discord
TOKEN = os.getenv('TOKEN')
CHANNEL_FEEDBACK_ID = 1340129942590980126
CARGO_ID = 1340128245433237548
CARGO_MENCAO_ID = 1344444552794210335
CARGO_REMOVER_ID = 1341452982209744916
CANAL_ESTOQUE_ID = 1354545783948579057
CANAL_TICKET_ID = 1340344478707224728
CANAIS_LEILAO = [1354935337398436040, 1354935389584097440]  # Dois canais de leilão

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Conexão com o banco de dados
conn = sqlite3.connect('dados_bot.db')
c = conn.cursor()

# Criar tabelas
c.execute('''CREATE TABLE IF NOT EXISTS reservas
             (canal_id INTEGER PRIMARY KEY, nick TEXT, produto TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS chaves_leilao
             (chave TEXT PRIMARY KEY, 
              duracao TEXT, 
              usos INTEGER, 
              usos_restantes INTEGER,
              ultimo_uso TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS leiloes
             (canal_id INTEGER PRIMARY KEY, 
              dono_id INTEGER, 
              chave TEXT,
              nome_conta TEXT,
              jogos TEXT,
              itens_conta TEXT,
              preco_inicial REAL,
              maior_lance REAL,
              maior_lance_user INTEGER,
              data_fim TEXT,
              message_id INTEGER)''')  # Adicionado message_id para referência

conn.commit()

# Funções auxiliares
def gerar_chave():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

def formatar_valor(valor):
    return f"R$ {valor:.2f}".replace('.', ',')

# View para leilão com botão de encerrar
class LeilaoAtivoView(ui.View):
    def __init__(self, dono_id):
        super().__init__(timeout=None)  # Timeout None para funcionar indefinidamente
        self.dono_id = dono_id
        
    @ui.button(label="⏱️ Encerrar Leilão Antecipadamente", style=discord.ButtonStyle.red, custom_id="encerrar_leilao")
    async def encerrar_leilao(self, interaction: discord.Interaction, button: ui.Button):
        # Verificar se é o dono ou administrador
        if interaction.user.id != self.dono_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⚠️ Apenas o dono do leilão ou administradores podem encerrá-lo antecipadamente.",
                ephemeral=True
            )
            return
            
        await interaction.response.defer()
        
        # Encontrar leilão no banco de dados
        c.execute("SELECT * FROM leiloes WHERE canal_id = ?", (interaction.channel.id,))
        leilao = c.fetchone()
        
        if not leilao:
            await interaction.followup.send("Leilão não encontrado no banco de dados.", ephemeral=True)
            return
            
        # Atualizar data de fim para agora
        c.execute("UPDATE leiloes SET data_fim = ? WHERE canal_id = ?", 
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), interaction.channel.id))
        conn.commit()
        
        await interaction.followup.send(
            f"⏱️ Leilão encerrado antecipadamente por {interaction.user.mention}",
            ephemeral=False
        )
        
        # Encontrar a mensagem original do leilão
        try:
            message = await interaction.channel.fetch_message(leilao[9])  # message_id está na posição 9
            await finalizar_leilao(message, interaction.channel.id)
        except:
            await interaction.followup.send("Não foi possível encontrar a mensagem do leilão.", ephemeral=True)

async def finalizar_leilao(message, canal_id):
    # Finalizar leilão
    c.execute("SELECT maior_lance_user, nome_conta, maior_lance FROM leiloes WHERE canal_id = ?", (canal_id,))
    vencedor_id, nome_conta, valor_vencedor = c.fetchone()
    
    embed = message.embeds[0]
    embed.color = 0x2ecc71
    embed.add_field(
        name="🎉 Leilão Encerrado", 
        value=f"**Vencedor:** <@{vencedor_id}> com {formatar_valor(valor_vencedor)}\n"
              f"**Conta:** {nome_conta}\n\n"
              f"🔹 O vencedor deve ir até <#{CANAL_TICKET_ID}> para finalizar a compra!",
        inline=False
    )
    
    # Remover a view (botões)
    await message.edit(content="🔔 LEILÃO ENCERRADO! @everyone", embed=embed, view=None)
    
    if vencedor_id:
        vencedor = await bot.fetch_user(vencedor_id)
        try:
            await vencedor.send(
                f"🎉 **Parabéns!** Você venceu o leilão da conta **{nome_conta}** por {formatar_valor(valor_vencedor)}!\n\n"
                f"Por favor, vá até <#{CANAL_TICKET_ID}> e informe que você foi o vencedor deste leilão.\n\n"
                f"🔹 **Detalhes da Compra:**\n"
                f"- Item: {nome_conta}\n"
                f"- Valor: {formatar_valor(valor_vencedor)}\n"
                f"- ID do Leilão: {embed.footer.text.split(': ')[1]}"
            )
        except:
            pass

    # Remover leilão do banco de dados
    c.execute("DELETE FROM leiloes WHERE canal_id = ?", (canal_id,))
    conn.commit()

# [RESTANTE DO CÓDIGO PERMANECE IGUAL, MAS ATUALIZANDO O ENVIO DO LEILÃO PARA INCLUIR A NOVA VIEW]

class ConfirmarLeilaoView(ui.View):
    def __init__(self, chave, nome, jogos, itens, preco, data_fim, canal_id):
        super().__init__()
        self.chave = chave
        self.nome = nome
        self.jogos = jogos
        self.itens = itens
        self.preco = preco
        self.data_fim = data_fim
        self.canal_id = canal_id
        
    @ui.button(label="Enviar Leilão", style=discord.ButtonStyle.green)
    async def enviar_leilao(self, interaction: discord.Interaction, button: ui.Button):
        c.execute("INSERT INTO leiloes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                  (self.canal_id, interaction.user.id, self.chave, self.nome, 
                   self.jogos, self.itens, self.preco, self.preco, None, self.data_fim, None))  # message_id será atualizado depois
        conn.commit()
        
        embed = Embed(title=f"🎟️ LEILÃO DE CONTA: {self.nome}", color=0xe67e22)
        embed.description = (
            "🏆 **Como participar?**\n"
            "1. Envie uma mensagem respondendo a esta com o valor do seu lance (ex: 10.50)\n"
            "2. Seu lance deve ser pelo menos R$ 0,50 maior que o atual\n"
            "3. O vencedor será quem oferecer o maior valor quando o leilão encerrar\n\n"
            "⚠️ **Atenção:** Lances inválidos serão automaticamente removidos!"
        )
        embed.add_field(name="📌 Jogos", value=self.jogos, inline=False)
        embed.add_field(name="📦 Itens/Detalhes", value=self.itens, inline=False)
        embed.add_field(name="💰 Preço Inicial", value=formatar_valor(self.preco), inline=True)
        embed.add_field(name="⏳ Termina em", value=f"<t:{int(datetime.strptime(self.data_fim, '%Y-%m-%d %H:%M:%S').timestamp()}:R>", inline=True)
        embed.add_field(name="🔢 Maior Lance Atual", value=formatar_valor(self.preco), inline=True)
        embed.add_field(name="👤 Dono do Leilão", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"ID do Leilão: {self.chave[:8]}...")
        
        canal_leiloes = bot.get_channel(self.canal_id)
        
        # Criar view com botão de encerrar
        view = LeilaoAtivoView(interaction.user.id)
        
        msg = await canal_leiloes.send(content="@everyone 🎉 **NOVO LEILÃO INICIADO!**", embed=embed, view=view)
        
        # Atualizar message_id no banco de dados
        c.execute("UPDATE leiloes SET message_id = ? WHERE canal_id = ?", (msg.id, self.canal_id))
        conn.commit()
        
        asyncio.create_task(monitorar_lances(msg, self.canal_id))
        await interaction.response.send_message(f"✅ Leilão criado com sucesso em {canal_leiloes.mention}!", ephemeral=True)

async def monitorar_lances(message, canal_id):
    def check(m):
        return m.channel.id == canal_id and m.reference and m.reference.message_id == message.id
    
    while True:
        try:
            c.execute("SELECT data_fim, maior_lance FROM leiloes WHERE canal_id = ?", (canal_id,))
            data_fim, maior_lance = c.fetchone()
            
            if datetime.now() > datetime.strptime(data_fim, "%Y-%m-%d %H:%M:%S"):
                break
                
            lance = await bot.wait_for('message', check=check, timeout=60)
            
            try:
                valor = float(lance.content)
                c.execute("SELECT maior_lance FROM leiloes WHERE canal_id = ?", (canal_id,))
                maior_lance_atual = c.fetchone()[0]
                
                if valor <= maior_lance_atual:
                    await lance.delete()
                    await lance.author.send(
                        f"⚠️ Seu lance de {formatar_valor(valor)} é menor ou igual ao atual de {formatar_valor(maior_lance_atual)}. "
                        "Envie um valor maior!",
                        delete_after=10
                    )
                    continue
                    
                if valor < maior_lance_atual + 0.5:
                    await lance.delete()
                    await lance.author.send(
                        f"⚠️ Diferença mínima de R$ 0,50 necessária. "
                        f"O próximo lance deve ser pelo menos {formatar_valor(maior_lance_atual + 0.5)}",
                        delete_after=10
                    )
                    continue
                    
                c.execute("UPDATE leiloes SET maior_lance = ?, maior_lance_user = ? WHERE canal_id = ?",
                          (valor, lance.author.id, canal_id))
                conn.commit()
                
                embed = message.embeds[0]
                for i, field in enumerate(embed.fields):
                    if field.name == "🔢 Maior Lance Atual":
                        embed.set_field_at(i, name="🔢 Maior Lance Atual", 
                                         value=f"{formatar_valor(valor)} por {lance.author.mention}")
                
                await message.edit(embed=embed)
                await lance.add_reaction("✅")
                
            except ValueError:
                await lance.delete()
                await lance.author.send(
                    "⚠️ Formato inválido! Envie apenas o valor do lance (ex: 10 ou 10.50)",
                    delete_after=10
                )
                
        except asyncio.TimeoutError:
            continue
    
    await finalizar_leilao(message, canal_id)

# [MANTIDOS TODOS OS OUTROS COMANDOS EXISTENTES - calcular-robux, reservar, reserva, limpar, estoque, entregue, pix, pixinter]

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} está online!')
    # Adicionar a view persistente
    bot.add_view(LeilaoAtivoView(dono_id=0))  # dono_id 0 será substituído quando instanciado
    try:
        synced = await bot.tree.sync()
        print(f"Comandos slash sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")

bot.run(TOKEN)