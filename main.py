import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
import asyncio
from flask import Flask
from threading import Thread
import discord
from discord import app_commands, ui, Embed, Interaction
from discord.ext import commands

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
CANAIS_LEILAO = [1354935337398436040, 1354935389584097440]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Conexão com o banco de dados
conn = sqlite3.connect('dados_bot.db', check_same_thread=False)
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
              message_id INTEGER)''')

c.execute('''CREATE TABLE IF NOT EXISTS cooldown_chaves
             (user_id INTEGER PRIMARY KEY,
              ultimo_uso TEXT)''')

conn.commit()

# Funções auxiliares
def gerar_chave():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

def formatar_valor(valor):
    return f"R$ {valor:,.2f}".replace('.', 'temp').replace(',', '.').replace('temp', ',')

def calcular_robux(quantidade, com_taxa):
    if com_taxa:
        valor = (quantidade / 1000) * 45.00
        gamepass = int(quantidade / 0.7)
    else:
        valor = (quantidade / 1000) * 35.00
        gamepass = quantidade
    return valor, gamepass

# Sistema de Leilão
class LanceTracker:
    def __init__(self, bot, canal_id):
        self.bot = bot
        self.canal_id = canal_id
        self.active = True
        self.current_bid = 0.0
        self.current_winner = None
        self.end_time = None
        self.message = None
        self.lock = asyncio.Lock()
        self.encerrado_por = None

    async def start(self, message, preco_inicial, data_fim):
        self.message = message
        self.current_bid = preco_inicial
        self.end_time = datetime.strptime(data_fim, "%Y-%m-%d %H:%M:%S")
        
        while self.active and datetime.now() < self.end_time:
            await asyncio.sleep(1)
        
        if self.active:  # Só chama finalize se não foi encerrado manualmente
            await self.finalize_auction()

    async def process_bid(self, message):
        async with self.lock:
            try:
                if not await self.is_valid_bid(message):
                    return

                bid_amount = float(message.content.replace(',', '.'))
                
                self.current_bid = bid_amount
                self.current_winner = message.author
                
                c.execute("""
                    UPDATE leiloes 
                    SET maior_lance = ?, maior_lance_user = ? 
                    WHERE canal_id = ?
                """, (bid_amount, message.author.id, self.canal_id))
                conn.commit()
                
                await self.update_auction_message(bid_amount, message.author)
                await message.add_reaction("✅")
                
                notification = await message.channel.send(
                    f"🎉 Novo lance! {message.author.mention} ofereceu {formatar_valor(bid_amount)}!",
                    delete_after=10
                )
                
            except ValueError:
                await message.delete()
                await self.send_error(message.author, 
                                    "Formato inválido! Envie apenas o valor do lance em números. Exemplo: 10 ou 10.50")

    async def is_valid_bid(self, message):
        if (message.channel.id != self.canal_id or 
            not message.author or 
            message.author.bot or 
            not message.reference or 
            message.reference.message_id != self.message.id):
            return False
            
        try:
            bid_amount = float(message.content.replace(',', '.'))
        except ValueError:
            await message.delete()
            await self.send_error(message.author, "Formato inválido! Use apenas números. Ex: 10.50")
            return False
            
        if bid_amount <= self.current_bid:
            await message.delete()
            await self.send_error(message.author, 
                                f"Seu lance de {formatar_valor(bid_amount)} é menor ou igual ao lance atual de {formatar_valor(self.current_bid)}")
            return False
            
        if (bid_amount - self.current_bid) < 0.5:
            await message.delete()
            await self.send_error(message.author,
                                f"Diferença mínima de R$0,50 não atingida! Próximo lance deve ser pelo menos {formatar_valor(self.current_bid + 0.5)}")
            return False
            
        return True

    async def update_auction_message(self, bid_amount, bidder):
        embed = self.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "🔢 Maior Lance Atual":
                embed.set_field_at(i, name="🔢 Maior Lance Atual", 
                                 value=f"{formatar_valor(bid_amount)} por {bidder.mention}")
        
        await self.message.edit(embed=embed)

    async def send_error(self, user, error_msg):
        try:
            await user.send(f"❌ {error_msg}")
        except:
            await self.message.channel.send(
                f"{user.mention} ❌ {error_msg}",
                delete_after=10
            )

    async def finalize_auction(self, encerrado_por=None):
        self.active = False
        self.encerrado_por = encerrado_por
        
        c.execute("""
            SELECT nome_conta, jogos, itens_conta, preco_inicial, maior_lance, maior_lance_user, chave 
            FROM leiloes 
            WHERE canal_id = ?
        """, (self.canal_id,))
        nome_conta, jogos, itens, preco_inicial, maior_lance, vencedor_id, chave = c.fetchone()
        
        # Cria embed de encerramento
        embed = Embed(title=f"🏁 LEILÃO ENCERRADO: {nome_conta}", color=0x2ecc71)
        
        motivo_encerramento = "Tempo esgotado" if encerrado_por is None else f"Encerrado por {encerrado_por.mention}"
        embed.add_field(name="📝 Motivo do Encerramento", value=motivo_encerramento, inline=False)
        
        if vencedor_id:
            embed.add_field(name="🎉 Vencedor", value=f"<@{vencedor_id}> com {formatar_valor(maior_lance)}", inline=False)
            embed.add_field(name="💰 Valor Final", value=formatar_valor(maior_lance), inline=True)
        else:
            embed.add_field(name="ℹ️ Resultado", value="Nenhum lance válido foi realizado", inline=False)
            embed.add_field(name="💰 Preço Inicial", value=formatar_valor(preco_inicial), inline=True)
        
        embed.add_field(name="🎮 Jogos", value=jogos, inline=False)
        embed.add_field(name="📦 Itens/Detalhes", value=itens, inline=False)
        embed.add_field(name="🔑 ID do Leilão", value=chave[:8] + "...", inline=True)
        
        embed.set_footer(text=f"Leilão encerrado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Envia a nova mensagem de encerramento
        canal = self.bot.get_channel(self.canal_id)
        mensagem_encerramento = await canal.send(embed=embed)
        
        # Edita a mensagem original do leilão
        if self.message:
            await self.message.edit(content="🔔 LEILÃO ENCERRADO! @everyone", view=None)
        
        # Notifica o vencedor
        if vencedor_id:
            try:
                vencedor = await self.bot.fetch_user(vencedor_id)
                await vencedor.send(
                    f"🎉 **Parabéns!** Você venceu o leilão da conta **{nome_conta}** por {formatar_valor(maior_lance)}!\n\n"
                    f"Por favor, vá até <#{CANAL_TICKET_ID}> e informe que você foi o vencedor deste leilão.\n\n"
                    f"🔹 **Detalhes da Compra:**\n"
                    f"- Item: {nome_conta}\n"
                    f"- Valor: {formatar_valor(maior_lance)}\n"
                    f"- ID do Leilão: {chave[:8]}..."
                )
            except:
                pass

        # Remove do banco de dados
        c.execute("DELETE FROM leiloes WHERE canal_id = ?", (self.canal_id,))
        conn.commit()
        
        # Remove o tracker ativo
        if self.canal_id in active_trackers:
            del active_trackers[self.canal_id]

# Dicionário para armazenar trackers ativos
active_trackers = {}

def get_active_tracker(channel_id):
    return active_trackers.get(channel_id)

# Classes para o sistema de leilão
class LeilaoView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @ui.button(label="Adicionar Chave", style=discord.ButtonStyle.green, custom_id="add_key")
    async def add_key(self, interaction: discord.Interaction, button: ui.Button):
        # Verifica se é administrador (sem cooldown)
        if not interaction.user.guild_permissions.administrator:
            c.execute("SELECT ultimo_uso FROM cooldown_chaves WHERE user_id = ?", (interaction.user.id,))
            cooldown = c.fetchone()
            
            if cooldown:
                ultimo_uso = datetime.strptime(cooldown[0], "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - ultimo_uso) < timedelta(days=2):
                    await interaction.response.send_message(
                        "⏳ Você só pode usar uma chave a cada 2 dias! Por favor, aguarde.",
                        ephemeral=True
                    )
                    return
        
        modal = AdicionarChaveModal()
        await interaction.response.send_modal(modal)

class AdicionarChaveModal(ui.Modal, title="Adicionar Chave de Leilão"):
    chave = ui.TextInput(label="Chave de Leilão", placeholder="Cole a chave que você recebeu aqui")
    
    async def on_submit(self, interaction: discord.Interaction):
        c.execute("SELECT * FROM chaves_leilao WHERE chave = ?", (str(self.chave),))
        chave_info = c.fetchone()
        
        if not chave_info:
            await interaction.response.send_message("❌ Chave inválida ou já utilizada!", ephemeral=True)
            return
            
        if chave_info[3] <= 0:
            await interaction.response.send_message("❌ Esta chave já foi usada o máximo de vezes!", ephemeral=True)
            return
            
        canal_disponivel = None
        for canal_id in CANAIS_LEILAO:
            c.execute("SELECT 1 FROM leiloes WHERE canal_id = ?", (canal_id,))
            if not c.fetchone():
                canal_disponivel = canal_id
                break
                
        if not canal_disponivel:
            await interaction.response.send_message(
                "⚠️ Todos os canais de leilão estão ocupados no momento. Por favor, aguarde até que um leilão termine.",
                ephemeral=True
            )
            return
            
        c.execute("UPDATE chaves_leilao SET usos_restantes = usos_restantes - 1 WHERE chave = ?", (str(self.chave),))
        
        # Aplica cooldown apenas para não-administradores
        if not interaction.user.guild_permissions.administrator:
            c.execute("INSERT OR REPLACE INTO cooldown_chaves VALUES (?, ?)", 
                     (interaction.user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        conn.commit()
        
        embed = Embed(title="📝 Formulário de Leilão", color=0x3498db)
        embed.description = "Por favor, preencha as informações sobre a conta que será leiloada."
        
        view = FormularioLeilaoView(chave_info, canal_disponivel)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class FormularioLeilaoView(ui.View):
    def __init__(self, chave_info, canal_id):
        super().__init__()
        self.chave_info = chave_info
        self.canal_id = canal_id
        
    @ui.button(label="Preencher Formulário", style=discord.ButtonStyle.primary)
    async def preencher_form(self, interaction: discord.Interaction, button: ui.Button):
        modal = FormularioLeilaoModal(self.chave_info, self.canal_id)
        await interaction.response.send_modal(modal)

class FormularioLeilaoModal(ui.Modal, title="Formulário de Leilão"):
    def __init__(self, chave_info, canal_id):
        super().__init__()
        self.chave_info = chave_info
        self.canal_id = canal_id
        
    nome_conta = ui.TextInput(label="Nome da Conta")
    jogos = ui.TextInput(label="Jogos da Conta", style=discord.TextStyle.long,
                        placeholder="Separe por vírgulas (ex: Blox Fruits, Blue Lock)")
    itens = ui.TextInput(label="Itens/Detalhes da Conta", style=discord.TextStyle.long)
    preco = ui.TextInput(label="Preço Inicial (R$)")
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            preco_inicial = float(str(self.preco).replace(',', '.'))
        except ValueError:
            await interaction.response.send_message("❌ Por favor, insira um preço válido!", ephemeral=True)
            return
            
        duracao = self.chave_info[1]
        if 'd' in duracao:
            dias = int(duracao.split('d')[0])
            data_fim = datetime.now() + timedelta(days=dias)
        elif 'h' in duracao:
            horas = int(duracao.split('h')[0])
            data_fim = datetime.now() + timedelta(hours=horas)
        else:
            data_fim = datetime.now() + timedelta(days=1)
            
        embed = Embed(title="✅ Leilão Pronto para Envio", color=0x2ecc71)
        embed.add_field(name="Nome da Conta", value=str(self.nome_conta), inline=False)
        embed.add_field(name="Jogos", value=str(self.jogos), inline=False)
        embed.add_field(name="Itens/Detalhes", value=str(self.itens), inline=False)
        embed.add_field(name="Preço Inicial", value=formatar_valor(preco_inicial), inline=False)
        embed.add_field(name="Duração do Leilão", value=duracao, inline=False)
        embed.set_footer(text="Revise as informações antes de enviar!")
        
        view = ConfirmarLeilaoView(
            self.chave_info[0],
            str(self.nome_conta),
            str(self.jogos),
            str(self.itens),
            preco_inicial,
            data_fim.strftime("%Y-%m-%d %H:%M:%S"),
            self.canal_id
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
                   self.jogos, self.itens, self.preco, self.preco, None, self.data_fim, None))
        conn.commit()
        
        embed = Embed(title=f"🎟️ LEILÃO DE CONTA: {self.nome}", color=0xe67e22)
        embed.description = (
            "🏆 **Como participar?**\n"
            "1. Envie uma mensagem respondendo a esta com o valor do seu lance (ex: 10.50)\n"
            "2. Seu lance deve ser pelo menos R$ 0,50 maior que o atual\n"
            "3. O vencedor será quem oferecer o maior valor quando o leilão encerrar\n\n"
            "📢 **Regras Importantes:**\n"
            "• Lances devem ser em números (ex: 10 ou 10.50)\n"
            "• Diferença mínima entre lances: R$ 0,50\n"
            "• Não é permitido cancelar lances após enviados\n"
            "• O vencedor terá 24h para realizar o pagamento\n\n"
            "⚠️ **Atenção:** Lances inválidos serão automaticamente removidos!"
        )
        embed.add_field(name="📌 Jogos Inclusos", value=self.jogos, inline=False)
        embed.add_field(name="📦 Itens/Detalhes da Conta", value=self.itens, inline=False)
        embed.add_field(name="💰 Preço Inicial", value=formatar_valor(self.preco), inline=True)
        embed.add_field(name="⏳ Termina em", value=f"<t:{int(datetime.strptime(self.data_fim, '%Y-%m-%d %H:%M:%S').timestamp())}:R>", inline=True)
        embed.add_field(name="🔢 Maior Lance Atual", value=formatar_valor(self.preco), inline=True)
        embed.add_field(name="👤 Dono do Leilão", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"ID do Leilão: {self.chave[:8]}...")
        
        canal_leiloes = bot.get_channel(self.canal_id)
        view = LeilaoAtivoView(interaction.user.id)
        msg = await canal_leiloes.send(content="@everyone 🎉 **NOVO LEILÃO INICIADO!**", embed=embed, view=view)
        
        c.execute("UPDATE leiloes SET message_id = ? WHERE canal_id = ?", (msg.id, self.canal_id))
        conn.commit()
        
        tracker = LanceTracker(bot, self.canal_id)
        active_trackers[self.canal_id] = tracker
        asyncio.create_task(tracker.start(msg, self.preco, self.data_fim))
        
        await interaction.response.send_message(f"✅ Leilão criado com sucesso em {canal_leiloes.mention}!", ephemeral=True)

class LeilaoAtivoView(ui.View):
    def __init__(self, dono_id):
        super().__init__(timeout=None)
        self.dono_id = dono_id
        
    @ui.button(label="⏱️ Encerrar Leilão", style=discord.ButtonStyle.red, custom_id="encerrar_leilao")
    async def encerrar_leilao(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.dono_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Apenas o dono do leilão ou administradores podem encerrá-lo!", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        tracker = get_active_tracker(interaction.channel.id)
        if tracker:
            await tracker.finalize_auction(encerrado_por=interaction.user)
            await interaction.followup.send(f"⏱️ Leilão encerrado por {interaction.user.mention}")
        else:
            await interaction.followup.send("❌ Nenhum leilão ativo encontrado neste canal.", ephemeral=True)

# Evento para processar lances
@bot.event
async def on_message(message):
    await bot.process_commands(message)
    
    if not message.author.bot and message.guild:
        tracker = get_active_tracker(message.channel.id)
        if tracker and tracker.active:
            await tracker.process_bid(message)

# [RESTANTE DOS COMANDOS SLASH E EVENTOS MANTIDOS IGUAL AO CÓDIGO ANTERIOR]

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} está online!')
    bot.add_view(LeilaoView())
    bot.add_view(LeilaoAtivoView(dono_id=0))
    try:
        synced = await bot.tree.sync()
        print(f"Comandos slash sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")

bot.run(TOKEN)