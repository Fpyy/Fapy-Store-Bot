from flask import Flask
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands
import os
import sqlite3
from discord import Embed

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

TOKEN = os.getenv('TOKEN')  # Lê o token da variável de ambiente
CHANNEL_FEEDBACK_ID = 1340129942590980126  # ID do canal de feedbacks
CARGO_ID = 1340128245433237548  # ID do cargo que será dado aos membros
CARGO_MENCAO_ID = 1344444552794210335  # ID do cargo para mencionar
CARGO_REMOVER_ID = 1341452982209744916  # ID do cargo que será removido
CANAL_ESTOQUE_ID = 1354545783948579057  # NOVO ID do canal para enviar a mensagem de estoque
CANAL_TICKET_ID = 1340344478707224728  # ID do canal para abrir ticket

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Permite que o bot acesse informações dos membros

bot = commands.Bot(command_prefix="!", intents=intents)  # Prefixo "!"

# Conecta ao banco de dados SQLite (ou cria se não existir)
conn = sqlite3.connect('reservas.db')
c = conn.cursor()

# Cria a tabela de reservas se não existir
c.execute('''CREATE TABLE IF NOT EXISTS reservas
             (canal_id INTEGER PRIMARY KEY, nick TEXT, produto TEXT)''')
conn.commit()

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} está online!')
    try:
        synced = await bot.tree.sync()  # Sincroniza os slash commands
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar slash commands: {e}")

# Slash Command: /reservar
@bot.tree.command(name="reservar", description="Faz uma reserva")
@app_commands.describe(nick="Nick do cliente", produto="Produto reservado")
async def reservar(interaction: discord.Interaction, nick: str, produto: str):
    # Salva a reserva no banco de dados
    canal_id = interaction.channel.id
    c.execute('INSERT OR REPLACE INTO reservas (canal_id, nick, produto) VALUES (?, ?, ?)',
              (canal_id, nick, produto))
    conn.commit()

    # Muda o nome do canal para "⏳・reservado"
    try:
        await interaction.channel.edit(name="⏳・reservado")
        print(f"Nome do canal alterado para ⏳・reservado")
    except Exception as e:
        print(f"Erro ao alterar o nome do canal: {e}")

    # Adiciona o cargo de remoção a todos os membros no canal
    cargo_remover = interaction.guild.get_role(CARGO_REMOVER_ID)
    if cargo_remover:
        for member in interaction.channel.members:
            try:
                await member.add_roles(cargo_remover)
                print(f"Cargo de remoção adicionado para {member.display_name}")
            except Exception as e:
                print(f"Erro ao adicionar cargo para {member.display_name}: {e}")
    else:
        print("Cargo de remoção não encontrado")

    # Mensagem pública no canal
    mensagem_publica = (
        "Reserva realizada com sucesso!\n"
        "Para acessá-la, utilize o comando `/reserva`."
    )
    await interaction.response.send_message(mensagem_publica)

# Slash Command: /reserva
@bot.tree.command(name="reserva", description="Mostra a reserva atual")
async def reserva(interaction: discord.Interaction):
    # Busca a reserva no banco de dados
    canal_id = interaction.channel.id
    c.execute('SELECT nick, produto FROM reservas WHERE canal_id = ?', (canal_id,))
    reserva = c.fetchone()

    if reserva:
        nick, produto = reserva
        # Obtém o cargo para mencionar
        cargo_menção = interaction.guild.get_role(CARGO_MENCAO_ID)
        if not cargo_menção:
            await interaction.response.send_message("Cargo de menção não encontrado. Verifique o ID do cargo.", ephemeral=True)
            return

        # Mensagem formatada
        mensagem = (
            "Reserva:\n"
            f"**Nick**: {nick}\n"
            f"**Produto**: {produto}\n"
            f"{cargo_menção.mention}"  # Menciona o cargo
        )
        await interaction.response.send_message(mensagem)
    else:
        await interaction.response.send_message("Nenhuma reserva foi feita ainda neste canal.", ephemeral=True)

# Slash Command: /limpar
@bot.tree.command(name="limpar", description="Limpa a reserva atual")
async def limpar(interaction: discord.Interaction):
    canal_id = interaction.channel.id
    c.execute('DELETE FROM reservas WHERE canal_id = ?', (canal_id,))
    conn.commit()

    if c.rowcount > 0:
        await interaction.response.send_message("Reserva limpa com sucesso!", ephemeral=True)
    else:
        await interaction.response.send_message("Nenhuma reserva foi feita ainda neste canal.", ephemeral=True)

# Slash Command: /calcular-robux-com-taxa
@bot.tree.command(name="calcular-robux-com-taxa", description="Calcula o valor em reais de Robux com taxa")
@app_commands.describe(quantidade="Quantidade de Robux")
async def calcular_robux_com_taxa(interaction: discord.Interaction, quantidade: int):
    # Valor de 1000 Robux com taxa = R$45,00
    valor_por_1000_robux = 45.00
    valor_total = (quantidade / 1000) * valor_por_1000_robux

    # Mensagem formatada
    mensagem = f"O valor de {quantidade} Robux com taxa = R${valor_total:.2f}"
    await interaction.response.send_message(mensagem)

# Slash Command: /calcular-robux-sem-taxa
@bot.tree.command(name="calcular-robux-sem-taxa", description="Calcula o valor em reais de Robux sem taxa")
@app_commands.describe(quantidade="Quantidade de Robux")
async def calcular_robux_sem_taxa(interaction: discord.Interaction, quantidade: int):
    # Valor de 1000 Robux sem taxa = R$35,00
    valor_por_1000_robux = 35.00
    valor_total = (quantidade / 1000) * valor_por_1000_robux

    # Mensagem formatada
    mensagem = f"O valor de {quantidade} Robux sem taxa = R${valor_total:.2f}"
    await interaction.response.send_message(mensagem)

# Comando de prefixo: !estoque
@bot.command()
async def estoque(ctx, quantidade: int):
    # Verifica se o canal de estoque existe
    canal_estoque = bot.get_channel(CANAL_ESTOQUE_ID)
    if not canal_estoque:
        await ctx.send("Canal de estoque não encontrado. Verifique o ID do canal.")
        return

    # Mensagem formatada melhorada
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

    # Envia a mensagem no canal de estoque
    await canal_estoque.send(mensagem)
    await ctx.send("✅ Mensagem de estoque enviada com sucesso!", ephemeral=True)

# Comando de prefixo: !entregue
@bot.command()
async def entregue(ctx, membro: discord.Member):
    # Apaga a mensagem do usuário
    await ctx.message.delete()

    # Obtém os cargos pelo ID
    cargo_entregue = ctx.guild.get_role(CARGO_ID)
    cargo_remover = ctx.guild.get_role(CARGO_REMOVER_ID)

    if not cargo_entregue or not cargo_remover:
        await ctx.send("Cargo não encontrado. Verifique os IDs dos cargos.", delete_after=10)
        return

    # Muda o nome do canal para "✅・entregue"
    try:
        await ctx.channel.edit(name="✅・entregue")
        print(f"Nome do canal alterado para ✅・entregue")
    except Exception as e:
        print(f"Erro ao alterar o nome do canal: {e}")

    # Envia a mensagem de feedback no canal
    feedback_message = (
        f"Tudo certo com sua compra, {membro.mention}?\n"
        "**Não esqueça de avaliar!** Isso nos ajuda muito.\n"
        f"Deixe seu feedback aqui: <#{CHANNEL_FEEDBACK_ID}>\n"
        f"{cargo_entregue.mention}"
    )
    await ctx.send(feedback_message)

    # Cria e envia a embed na DM do membro
    embed = Embed(
        title="ALERTA!",
        description="Sua compra foi entregue! Para verificar as provas, cheque o ticket da loja!\n\n"
                   "Não se esqueça de deixar uma avaliação se gostou da compra! Nos ajuda muito.",
        color=0x00ff00  # Verde
    )
    embed.set_thumbnail(url="https://static.vecteezy.com/ti/vetor-gratis/p1/12528049-entrega-de-compra-de-loja-design-plano-pacote-de-pedido-aberto-produtos-por-atacado-receber-encomenda-postal-descompactar-caixa-icone-de-glifoial-vetor.jpg")
    
    try:
        await membro.send(embed=embed)
        print(f"Mensagem de entrega enviada para {membro.display_name}")
    except Exception as e:
        print(f"Erro ao enviar mensagem para {membro.display_name}: {e}")

    # Adiciona o cargo "entregue" e remove o cargo "remover" para o membro mencionado
    try:
        # Remove o cargo "remover" (se o membro tiver)
        if cargo_remover in membro.roles:
            await membro.remove_roles(cargo_remover)
            print(f"Cargo removido de {membro.display_name}")

        # Adiciona o cargo "entregue" (se o membro não tiver)
        if cargo_entregue not in membro.roles:
            await membro.add_roles(cargo_entregue)
            print(f"Cargo dado para {membro.display_name}")
    except Exception as e:
        print(f"Erro ao gerenciar cargos para {membro.display_name}: {e}")

# Comando de prefixo: !pix
@bot.command()
async def pix(ctx):
    mensagem = (
        "Chave Pix: **0d8656b8-470e-4e0c-ac22-233ab0aa22ae**\n"
        "Tipo de chave: **Chave aleatória**\n\n"
        "*Após o pagamento, envie o comprovante da sua transação!*"
    )
    await ctx.send(mensagem)

# Comando de prefixo: !pixinter
@bot.command()
async def pixinter(ctx):
    mensagem = (
        "Chave Pix: **facinlaras0511@gmail.com**\n"
        "Tipo de chave: **E-mail**\n\n"
        "*Após o pagamento, envie o comprovante da sua transação!*"
    )
    await ctx.send(mensagem)

bot.run(TOKEN)