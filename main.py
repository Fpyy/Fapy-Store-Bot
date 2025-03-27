from flask import Flask
from threading import Thread
import discord
from discord import app_commands, ui, Embed, Interaction
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

# Sistema de Leilão Refatorado
class LanceTracker:
    def __init__(self, bot, canal_id):
        self.bot = bot
        self.canal_id = canal_id
        self.active = True
        self.current_bid = 0.0
        self.current_winner = None
        self.end_time = None
        self.message = None

    async def start(self, message, preco_inicial, data_fim):
        self.message = message
        self.current_bid = preco_inicial
        self.end_time = datetime.strptime(data_fim, "%Y-%m-%d %H:%M:%S")
        
        while self.active and datetime.now() < self.end_time:
            try:
                await self.process_bids()
            except Exception as e:
                print(f"Erro no processamento de lances: {e}")
                await asyncio.sleep(5)
        
        await self.finalize_auction()

    async def process_bids(self):
        def check(m):
            return (m.channel.id == self.canal_id and 
                    not m.author.bot and
                    m.reference and 
                    m.reference.message_id == self.message.id)
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            await self.validate_bid(msg)
        except asyncio.TimeoutError:
            pass

    async def validate_bid(self, message):
        try:
            bid_amount = float(message.content.replace(',', '.'))
            
            # Verifica se o lance é válido
            if bid_amount <= self.current_bid:
                await message.delete()
                await self.send_error(message.author, 
                                    f"Seu lance de {formatar_valor(bid_amount)} é menor ou igual ao lance atual de {formatar_valor(self.current_bid)}")
                return
                
            if (bid_amount - self.current_bid) < 0.5:
                await message.delete()
                await self.send_error(message.author,
                                    f"Diferença mínima de R$0,50 não atingida! Próximo lance deve ser pelo menos {formatar_valor(self.current_bid + 0.5)}")
                return
                
            # Lance válido - atualiza
            self.current_bid = bid_amount
            self.current_winner = message.author
            
            # Atualiza no banco de dados
            c.execute("""
                UPDATE leiloes 
                SET maior_lance = ?, maior_lance_user = ? 
                WHERE canal_id = ?
            """, (bid_amount, message.author.id, self.canal_id))
            conn.commit()
            
            # Atualiza a mensagem do leilão
            embed = self.message.embeds[0]
            for i, field in enumerate(embed.fields):
                if field.name == "🔢 Maior Lance Atual":
                    embed.set_field_at(i, name="🔢 Maior Lance Atual", 
                                     value=f"{formatar_valor(bid_amount)} por {message.author.mention}")
            
            await self.message.edit(embed=embed)
            await message.add_reaction("✅")
            
            # Notificação temporária
            notification = await self.message.channel.send(
                f"🎉 Novo lance! {message.author.mention} ofereceu {formatar_valor(bid_amount)}!",
                delete_after=10
            )
            
        except ValueError:
            await message.delete()
            await self.send_error(message.author, 
                                "Formato inválido! Envie apenas o valor do lance em números. Exemplo: 10 ou 10.50")

    async def send_error(self, user, error_msg):
        try:
            await user.send(f"❌ {error_msg}")
        except:
            # Se não puder enviar DM, envia como resposta efêmera
            await self.message.channel.send(
                f"{user.mention} ❌ {error_msg}",
                delete_after=10
            )

    async def finalize_auction(self):
        self.active = False
        c.execute("""
            SELECT nome_conta, maior_lance, maior_lance_user 
            FROM leiloes 
            WHERE canal_id = ?
        """, (self.canal_id,))
        nome_conta, maior_lance, vencedor_id = c.fetchone()
        
        embed = self.message.embeds[0]
        embed.color = 0x2ecc71
        embed.add_field(
            name="🎉 Leilão Encerrado", 
            value=f"**Vencedor:** <@{vencedor_id}> com {formatar_valor(maior_lance)}\n"
                  f"**Conta:** {nome_conta}\n\n"
                  f"🔹 O vencedor deve ir até <#{CANAL_TICKET_ID}> para finalizar a compra!",
            inline=False
        )
        
        await self.message.edit(content="🔔 LEILÃO ENCERRADO! @everyone", embed=embed, view=None)
        
        if vencedor_id:
            try:
                vencedor = await self.bot.fetch_user(vencedor_id)
                await vencedor.send(
                    f"🎉 **Parabéns!** Você venceu o leilão da conta **{nome_conta}** por {formatar_valor(maior_lance)}!\n\n"
                    f"Por favor, vá até <#{CANAL_TICKET_ID}> e informe que você foi o vencedor deste leilão.\n\n"
                    f"🔹 **Detalhes da Compra:**\n"
                    f"- Item: {nome_conta}\n"
                    f"- Valor: {formatar_valor(maior_lance)}\n"
                    f"- ID do Leilão: {embed.footer.text.split(': ')[1]}"
                )
            except:
                pass

        c.execute("DELETE FROM leiloes WHERE canal_id = ?", (self.canal_id,))
        conn.commit()

# Classes para o sistema de leilão
class LeilaoView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @ui.button(label="Adicionar Chave", style=discord.ButtonStyle.green, custom_id="add_key")
    async def add_key(self, interaction: discord.Interaction, button: ui.Button):
        # Verificação de cooldown (mesmo código anterior)
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
        # Verificação e processamento da chave (mesmo código anterior)
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
        
        # Inicia o tracker de lances
        tracker = LanceTracker(bot, self.canal_id)
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
        
        c.execute("SELECT * FROM leiloes WHERE canal_id = ?", (interaction.channel.id,))
        leilao = c.fetchone()
        
        if not leilao:
            await interaction.followup.send("Leilão não encontrado.", ephemeral=True)
            return
            
        # Atualiza o tempo de término para agora
        c.execute("UPDATE leiloes SET data_fim = ? WHERE canal_id = ?", 
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), interaction.channel.id))
        conn.commit()
        
        await interaction.followup.send(f"⏱️ Leilão encerrado antecipadamente por {interaction.user.mention}")

# Comandos Slash (mantidos os mesmos do código original)
@bot.tree.command(name="calcular-robux", description="Calcula o valor em reais para uma quantidade de Robux")
@app_commands.describe(quantidade="Quantidade de Robux")
async def calcular_robux(interaction: discord.Interaction, quantidade: int):
    await interaction.response.defer()
    
    valor_com_taxa, gamepass_com_taxa = calcular_robux(quantidade, True)
    valor_sem_taxa, gamepass_sem_taxa = calcular_robux(quantidade, False)
    
    embed = Embed(title="💰 Cálculo de Robux", color=0x3498db)
    embed.add_field(
        name=f"🔹 {quantidade} Robux com taxa (R$ 0,045 por Robux)",
        value=(
            f"**Valor:** {formatar_valor(valor_com_taxa)}\n"
            f"**Preço da Gamepass:** {gamepass_com_taxa} Robux\n"
            f"(Para receber {quantidade} Robux após a taxa de 30%)"
        ),
        inline=False
    )
    embed.add_field(
        name=f"🔸 {quantidade} Robux sem taxa (R$ 0,035 por Robux)",
        value=(
            f"**Valor:** {formatar_valor(valor_sem_taxa)}\n"
            f"**Preço da Gamepass:** {gamepass_sem_taxa} Robux"
        ),
        inline=False
    )
    embed.set_footer(text="Os valores podem variar conforme a cotação atual")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="reservar", description="Faz uma reserva")
@app_commands.describe(nick="Nick do cliente", produto="Produto reservado")
async def reservar(interaction: discord.Interaction, nick: str, produto: str):
    canal_id = interaction.channel.id
    c.execute('INSERT OR REPLACE INTO reservas (canal_id, nick, produto) VALUES (?, ?, ?)',
              (canal_id, nick, produto))
    conn.commit()

    try:
        await interaction.channel.edit(name="⏳・reservado")
        cargo_remover = interaction.guild.get_role(CARGO_REMOVER_ID)
        if cargo_remover:
            for member in interaction.channel.members:
                try:
                    await member.add_roles(cargo_remover)
                except:
                    pass
    except Exception as e:
        print(f"Erro: {e}")

    await interaction.response.send_message(
        "✅ Reserva realizada com sucesso!\nPara acessá-la, utilize o comando `/reserva`."
    )

@bot.tree.command(name="reserva", description="Mostra a reserva atual")
async def reserva(interaction: discord.Interaction):
    canal_id = interaction.channel.id
    c.execute('SELECT nick, produto FROM reservas WHERE canal_id = ?', (canal_id,))
    reserva = c.fetchone()

    if reserva:
        nick, produto = reserva
        cargo_menção = interaction.guild.get_role(CARGO_MENCAO_ID)
        mensagem = (
            "📋 **Reserva Atual**\n"
            f"**👤 Nick:** {nick}\n"
            f"**📦 Produto:** {produto}\n"
            f"{cargo_menção.mention if cargo_menção else ''}"
        )
        await interaction.response.send_message(mensagem)
    else:
        await interaction.response.send_message("ℹ️ Nenhuma reserva foi feita ainda neste canal.", ephemeral=True)

@bot.tree.command(name="limpar", description="Limpa a reserva atual")
async def limpar(interaction: discord.Interaction):
    canal_id = interaction.channel.id
    c.execute('DELETE FROM reservas WHERE canal_id = ?', (canal_id,))
    conn.commit()
    await interaction.response.send_message(
        "🧹 Reserva limpa com sucesso!" if c.rowcount > 0 
        else "ℹ️ Nenhuma reserva para limpar neste canal.",
        ephemeral=True
    )

@bot.tree.command(name="estoque", description="Anuncia novo estoque de Robux")
@app_commands.describe(quantidade="Quantidade de Robux disponível")
async def estoque(interaction: discord.Interaction, quantidade: int):
    if interaction.channel.id != CANAL_ESTOQUE_ID:
        await interaction.response.send_message("⚠️ Este comando só pode ser usado no canal de estoque!", ephemeral=True)
        return

    embed = Embed(title="🚀 NOVO ESTOQUE DISPONÍVEL!", color=0x00ff00)
    embed.description = (
        f"**📦 Quantidade:** `{quantidade:,}` Robux (prontos para entrega!)\n"
        f"**💳 Preço especial:** Melhor custo-benefício do mercado!\n\n"
        f"🔹 **Como comprar?**\n"
        f"1. Abra um ticket em <#{CANAL_TICKET_ID}>\n"
        "2. Nos informe quanto Robux deseja\n"
        "3. Receba seu Robux em minutos!\n\n"
        "⚠️ **ATENÇÃO:** Estoque limitado! Garanta já o seu!"
    )
    await interaction.response.send_message("@everyone", embed=embed)

@bot.tree.command(name="entregue", description="Marca uma compra como entregue")
@app_commands.describe(membro="Membro que recebeu a compra")
async def entregue(interaction: discord.Interaction, membro: discord.Member):
    await interaction.response.defer()
    
    cargo_entregue = interaction.guild.get_role(CARGO_ID)
    cargo_remover = interaction.guild.get_role(CARGO_REMOVER_ID)

    if not cargo_entregue or not cargo_remover:
        await interaction.followup.send("❌ Cargos não configurados corretamente!", ephemeral=True)
        return

    try:
        await interaction.channel.edit(name="✅・entregue")
    except:
        pass

    await interaction.followup.send(
        f"✅ Tudo certo com sua compra, {membro.mention}?\n"
        f"**Não esqueça de avaliar!** Deixe seu feedback aqui: <#{CHANNEL_FEEDBACK_ID}>\n"
        f"{cargo_entregue.mention}"
    )

    embed = Embed(
        title="✅ COMPRA ENTREGUE!",
        description=(
            "Sua compra foi entregue! Para verificar as provas, cheque o ticket da loja.\n\n"
            "Não se esqueça de deixar uma avaliação se gostou da compra! Nos ajuda muito."
        ),
        color=0x00ff00
    )
    embed.set_thumbnail(url="https://static.vecteezy.com/ti/vetor-gratis/p1/12528049-entrega-de-compra-de-loja-design-plano-pacote-de-pedido-aberto-produtos-por-atacado-receber-encomenda-postal-descompactar-caixa-icone-de-glifoial-vetor.jpg")
    
    try:
        await membro.send(embed=embed)
    except:
        pass

    try:
        if cargo_remover in membro.roles:
            await membro.remove_roles(cargo_remover)
        if cargo_entregue not in membro.roles:
            await membro.add_roles(cargo_entregue)
    except:
        pass

@bot.tree.command(name="pixinter", description="Mostra informações para pagamento via PIX internacional")
async def pixinter(interaction: discord.Interaction):
    embed = Embed(title="💳 Informações para PIX Internacional", color=0x9b59b6)
    embed.add_field(name="Chave PIX", value="facinlaras0511@gmail.com", inline=False)
    embed.add_field(name="Tipo de chave", value="E-mail", inline=False)
    embed.add_field(name="Instruções", value="Envie o valor exato da compra e o comprovante para o atendente", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Comando de prefixo (não slash)
@bot.command(name="pix")
async def pix(ctx):
    embed = Embed(title="💳 Informações para PIX", color=0x9b59b6)
    embed.add_field(name="Chave PIX", value="0d8656b8-470e-4e0c-ac22-233ab0aa22ae", inline=False)
    embed.add_field(name="Tipo de chave", value="Chave aleatória", inline=False)
    embed.add_field(name="Instruções", value="Envie o valor exato da compra e o comprovante para o atendente", inline=False)
    await ctx.send(embed=embed)

# Comandos do sistema de leilão
@bot.tree.command(name="gerarchave", description="Gera uma chave de leilão (apenas administradores)")
@app_commands.describe(duracao="Duração (ex: 1d, 12h, 3d)", usos="Número de usos permitidos")
@app_commands.checks.has_permissions(administrator=True)
async def gerar_chave_cmd(interaction: discord.Interaction, duracao: str, usos: int):
    chave = gerar_chave()
    c.execute("INSERT INTO chaves_leilao VALUES (?, ?, ?, ?, ?)", 
              (chave, duracao, usos, usos, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    
    embed = Embed(title="🔑 Chave Gerada com Sucesso!", color=0x00ff00)
    embed.add_field(name="Chave", value=f"`{chave}`", inline=False)
    embed.add_field(name="Duração", value=duracao, inline=True)
    embed.add_field(name="Usos", value=str(usos), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="leilao", description="Inicia o processo de criação de leilão")
async def leilao(interaction: discord.Interaction):
    embed = Embed(title="🏷️ Sistema de Leilão de Contas", color=0x3498db)
    embed.description = (
        "**Como participar?**\n"
        "1. Adquira uma chave de leilão com nossos vendedores\n"
        "2. Clique no botão abaixo para adicionar sua chave\n"
        "3. Preencha o formulário com os detalhes da sua conta\n"
        "4. Seu leilão será publicado automaticamente!\n\n"
        "**Pacotes disponíveis:**\n"
        "🕒 12h - R$ 10,00\n"
        "🌞 1 dia - R$ 15,00\n"
        "✨ 3 dias - R$ 25,00\n"
        "🔥 10 dias - R$ 50,00\n"
        "👑 Vitalício - R$ 75,00"
    )
    await interaction.response.send_message(embed=embed, view=LeilaoView())

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} está online!')
    # Adiciona as views persistentes
    bot.add_view(LeilaoView())
    bot.add_view(LeilaoAtivoView(dono_id=0))
    try:
        synced = await bot.tree.sync()
        print(f"Comandos slash sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")

bot.run(TOKEN)