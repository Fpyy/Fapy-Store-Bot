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
CANAL_LEILOES_ID = 1354935337398436040

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
             (chave TEXT PRIMARY KEY, duracao TEXT, usos INTEGER, usos_restantes INTEGER)''')

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
              data_fim TEXT)''')

conn.commit()

# Funções auxiliares
def gerar_chave():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

# Classes para o sistema de leilão
class LeilaoView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @ui.button(label="Adicionar Chave", style=ui.ButtonStyle.green, custom_id="add_key")
    async def add_key(self, interaction: discord.Interaction, button: ui.Button):
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
            
        c.execute("UPDATE chaves_leilao SET usos_restantes = usos_restantes - 1 WHERE chave = ?", (str(self.chave),))
        conn.commit()
        
        embed = Embed(title="📝 Formulário de Leilão", color=0x3498db)
        embed.description = "Por favor, preencha as informações sobre a conta que será leiloada."
        
        view = FormularioLeilaoView(chave_info)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class FormularioLeilaoView(ui.View):
    def __init__(self, chave_info):
        super().__init__()
        self.chave_info = chave_info
        
    @ui.button(label="Preencher Formulário", style=ui.ButtonStyle.primary)
    async def preencher_form(self, interaction: discord.Interaction, button: ui.Button):
        modal = FormularioLeilaoModal(self.chave_info)
        await interaction.response.send_modal(modal)

class FormularioLeilaoModal(ui.Modal, title="Formulário de Leilão"):
    def __init__(self, chave_info):
        super().__init__()
        self.chave_info = chave_info
        
    nome_conta = ui.TextInput(label="Nome da Conta")
    jogos = ui.TextInput(label="Jogos da Conta", placeholder="Separe por vírgulas (ex: Blox Fruits, Blue Lock)")
    itens = ui.TextInput(label="Itens/Detalhes da Conta", style=discord.TextStyle.long)
    preco = ui.TextInput(label="Preço Inicial (R$)")
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            preco_inicial = float(str(self.preco))
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
        embed.add_field(name="Preço Inicial", value=f"R$ {preco_inicial:.2f}", inline=False)
        embed.add_field(name="Duração do Leilão", value=duracao, inline=False)
        embed.set_footer(text="Revise as informações antes de enviar!")
        
        view = ConfirmarLeilaoView(
            self.chave_info[0],
            str(self.nome_conta),
            str(self.jogos),
            str(self.itens),
            preco_inicial,
            data_fim.strftime("%Y-%m-%d %H:%M:%S")
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ConfirmarLeilaoView(ui.View):
    def __init__(self, chave, nome, jogos, itens, preco, data_fim):
        super().__init__()
        self.chave = chave
        self.nome = nome
        self.jogos = jogos
        self.itens = itens
        self.preco = preco
        self.data_fim = data_fim
        
    @ui.button(label="Enviar Leilão", style=ui.ButtonStyle.green)
    async def enviar_leilao(self, interaction: discord.Interaction, button: ui.Button):
        c.execute("INSERT INTO leiloes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                  (interaction.channel.id, interaction.user.id, self.chave, self.nome, 
                   self.jogos, self.itens, self.preco, self.preco, None, self.data_fim))
        conn.commit()
        
        embed = Embed(title=f"🎟️ LEILÃO DE CONTA: {self.nome}", color=0xe67e22)
        embed.add_field(name="📌 Jogos", value=self.jogos, inline=False)
        embed.add_field(name="📦 Itens/Detalhes", value=self.itens, inline=False)
        embed.add_field(name="💰 Preço Inicial", value=f"R$ {self.preco:.2f}", inline=True)
        embed.add_field(name="⏳ Termina em", value=f"<t:{int(datetime.strptime(self.data_fim, '%Y-%m-%d %H:%M:%S').timestamp())}:R>", inline=True)
        embed.set_footer(text=f"Leilão criado por {interaction.user.display_name}")
        
        canal_leiloes = bot.get_channel(CANAL_LEILOES_ID)
        msg = await canal_leiloes.send(embed=embed)
        
        asyncio.create_task(monitorar_lances(msg, interaction.channel.id))
        await interaction.response.send_message("✅ Leilão criado com sucesso!", ephemeral=True)

async def monitorar_lances(message, canal_id):
    def check(m):
        return m.channel.id == CANAL_LEILOES_ID and m.reference and m.reference.message_id == message.id
    
    while True:
        try:
            c.execute("SELECT data_fim FROM leiloes WHERE canal_id = ?", (canal_id,))
            data_fim = c.fetchone()[0]
            
            if datetime.now() > datetime.strptime(data_fim, "%Y-%m-%d %H:%M:%S"):
                break
                
            lance = await bot.wait_for('message', check=check, timeout=60)
            
            try:
                valor = float(lance.content)
                c.execute("SELECT maior_lance FROM leiloes WHERE canal_id = ?", (canal_id,))
                maior_lance = c.fetchone()[0]
                
                if valor <= maior_lance + 0.5:
                    await lance.delete()
                    await lance.author.send("⚠️ Seu lance deve ser pelo menos R$ 0,50 maior que o atual!", delete_after=10)
                    continue
                    
                c.execute("UPDATE leiloes SET maior_lance = ?, maior_lance_user = ? WHERE canal_id = ?",
                          (valor, lance.author.id, canal_id))
                conn.commit()
                
                embed = message.embeds[0]
                for i, field in enumerate(embed.fields):
                    if field.name == "💰 Preço Inicial":
                        embed.set_field_at(i, name="💰 Maior Lance", value=f"R$ {valor:.2f} por {lance.author.mention}")
                
                await message.edit(embed=embed)
                await lance.add_reaction("✅")
                
            except ValueError:
                await lance.delete()
                await lance.author.send("⚠️ Por favor, envie apenas o valor do lance (ex: 10.50)", delete_after=10)
                
        except asyncio.TimeoutError:
            continue
    
    c.execute("SELECT maior_lance_user, nome_conta FROM leiloes WHERE canal_id = ?", (canal_id,))
    vencedor_id, nome_conta = c.fetchone()
    
    embed = message.embeds[0]
    embed.color = 0x2ecc71
    embed.add_field(name="🎉 Vencedor", value=f"<@{vencedor_id}>" if vencedor_id else "Nenhum lance", inline=False)
    embed.add_field(name="🔒 Leilão Encerrado", value=f"Obrigado a todos por participarem!", inline=False)
    
    await message.edit(embed=embed)
    
    if vencedor_id:
        vencedor = await bot.fetch_user(vencedor_id)
        await vencedor.send(f"🎉 Parabéns! Você venceu o leilão da conta **{nome_conta}**!\n"
                          f"Por favor, vá para <#{CANAL_TICKET_ID}> para finalizar sua compra!")

# Comandos existentes
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
        "Reserva realizada com sucesso!\nPara acessá-la, utilize o comando `/reserva`."
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
            "Reserva:\n"
            f"**Nick**: {nick}\n"
            f"**Produto**: {produto}\n"
            f"{cargo_menção.mention if cargo_menção else ''}"
        )
        await interaction.response.send_message(mensagem)
    else:
        await interaction.response.send_message("Nenhuma reserva foi feita ainda neste canal.", ephemeral=True)

@bot.tree.command(name="limpar", description="Limpa a reserva atual")
async def limpar(interaction: discord.Interaction):
    canal_id = interaction.channel.id
    c.execute('DELETE FROM reservas WHERE canal_id = ?', (canal_id,))
    conn.commit()
    await interaction.response.send_message(
        "Reserva limpa com sucesso!" if c.rowcount > 0 
        else "Nenhuma reserva foi feita ainda neste canal.",
        ephemeral=True
    )

@bot.tree.command(name="calcular-robux-com-taxa", description="Calcula o valor em reais de Robux com taxa")
@app_commands.describe(quantidade="Quantidade de Robux")
async def calcular_robux_com_taxa(interaction: discord.Interaction, quantidade: int):
    valor_total = (quantidade / 1000) * 45.00
    await interaction.response.send_message(f"O valor de {quantidade} Robux com taxa = R${valor_total:.2f}")

@bot.tree.command(name="calcular-robux-sem-taxa", description="Calcula o valor em reais de Robux sem taxa")
@app_commands.describe(quantidade="Quantidade de Robux")
async def calcular_robux_sem_taxa(interaction: discord.Interaction, quantidade: int):
    valor_total = (quantidade / 1000) * 35.00
    await interaction.response.send_message(f"O valor de {quantidade} Robux sem taxa = R${valor_total:.2f}")

@bot.command()
async def estoque(ctx, quantidade: int):
    canal_estoque = bot.get_channel(CANAL_ESTOQUE_ID)
    if not canal_estoque:
        await ctx.send("Canal de estoque não encontrado.", ephemeral=True)
        return

    mensagem = (
        "## 🚀 NOVO ESTOQUE DISPONÍVEL! 🚀\n\n"
        f"**📦 Quantidade:** `{quantidade:,}` Robux (prontos para entrega!)\n"
        f"**💳 Preço especial:** Melhor custo-benefício do mercado!\n\n"
        f"🔹 **Como comprar?**\n"
        f"1. Abra um ticket em <#{CANAL_TICKET_ID}>\n"
        "2. Nos informe quanto Robux deseja\n"
        "3. Receba seu Robux em minutos!\n\n"
        "⚠️ **ATENÇÃO:** Estoque limitado! Garanta já o seu! @everyone"
    )
    await canal_estoque.send(mensagem)
    await ctx.send("✅ Mensagem de estoque enviada com sucesso!", ephemeral=True)

@bot.command()
async def entregue(ctx, membro: discord.Member):
    await ctx.message.delete()
    cargo_entregue = ctx.guild.get_role(CARGO_ID)
    cargo_remover = ctx.guild.get_role(CARGO_REMOVER_ID)

    if not cargo_entregue or not cargo_remover:
        return

    try:
        await ctx.channel.edit(name="✅・entregue")
    except:
        pass

    await ctx.send(
        f"Tudo certo com sua compra, {membro.mention}?\n"
        f"**Não esqueça de avaliar!** Deixe seu feedback aqui: <#{CHANNEL_FEEDBACK_ID}>\n"
        f"{cargo_entregue.mention}"
    )

    embed = Embed(
        title="ALERTA!",
        description="Sua compra foi entregue! Para verificar as provas, cheque o ticket da loja!\n\n"
                   "Não se esqueça de deixar uma avaliação se gostou da compra! Nos ajuda muito.",
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

@bot.command()
async def pix(ctx):
    await ctx.send(
        "Chave Pix: **0d8656b8-470e-4e0c-ac22-233ab0aa22ae**\n"
        "Tipo de chave: **Chave aleatória**\n\n"
        "*Após o pagamento, envie o comprovante da sua transação!*"
    )

@bot.command()
async def pixinter(ctx):
    await ctx.send(
        "Chave Pix: **facinlaras0511@gmail.com**\n"
        "Tipo de chave: **E-mail**\n\n"
        "*Após o pagamento, envie o comprovante da sua transação!*"
    )

# Comandos do sistema de leilão
@bot.tree.command(name="gerarchave", description="Gera uma chave de leilão (apenas administradores)")
@app_commands.describe(duracao="Duração (ex: 1d, 12h, 3d)", usos="Número de usos permitidos")
@app_commands.checks.has_permissions(administrator=True)
async def gerar_chave_cmd(interaction: discord.Interaction, duracao: str, usos: int):
    chave = gerar_chave()
    c.execute("INSERT INTO chaves_leilao VALUES (?, ?, ?, ?)", (chave, duracao, usos, usos))
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
    await bot.tree.sync()

bot.run(TOKEN)