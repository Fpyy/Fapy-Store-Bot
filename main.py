import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
import asyncio
import aiohttp
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
CANAIS_LEILAO = [1356427244171563089, 1354935389584097440]
TEMPO_LIMPEZA_LEILAO = 5 * 60  # 5 minutos em segundos
WEBHOOK_LEILAO_LOGS = "https://discord.com/api/webhooks/1358932314012389669/wdA0qeOI5O7r5joS0V18DFNnRt7paYqo0jRq4UxMl2XiZdFbLeWn8c7e1xBD0X6EhStu"

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

def calcular_valor_robux(quantidade, com_taxa):
    if com_taxa:
        valor = (quantidade / 1000) * 45.00
        gamepass = int(quantidade / 0.7)
    else:
        valor = (quantidade / 1000) * 35.00
        gamepass = quantidade
    return valor, gamepass

async def enviar_log_leilao(mensagem: str):
    """Envia logs para o webhook de leilões"""
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_LEILAO_LOGS, session=session)
        try:
            await webhook.send(mensagem)
        except Exception as e:
            print(f"Erro ao enviar log: {e}")

##############################################
## CLASSES DE VIEW
##############################################

class LeilaoView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @ui.button(label="Adicionar Chave", style=discord.ButtonStyle.green, custom_id="add_key")
    async def add_key(self, interaction: Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            c.execute("SELECT ultimo_uso FROM cooldown_chaves WHERE user_id = ?", (interaction.user.id,))
            cooldown = c.fetchone()
            
            if cooldown and (datetime.now() - datetime.strptime(cooldown[0], "%Y-%m-%d %H:%M:%S")) < timedelta(hours=1):
                await interaction.response.send_message("⏳ Aguarde 1 hora entre usos de chaves!", ephemeral=True)
                return
                
        await interaction.response.send_modal(AdicionarChaveModal())

class AdicionarChaveModal(ui.Modal, title="Adicionar Chave"):
    chave = ui.TextInput(label="Chave de Leilão", placeholder="Cole a chave recebida")
    
    async def on_submit(self, interaction: Interaction):
        c.execute("SELECT * FROM chaves_leilao WHERE chave = ?", (str(self.chave),))
        chave_info = c.fetchone()
        
        if not chave_info or chave_info[3] <= 0:
            await interaction.response.send_message("❌ Chave inválida ou já usada!", ephemeral=True)
            return
            
        canal_id = next((cid for cid in CANAIS_LEILAO 
                        if not c.execute("SELECT 1 FROM leiloes WHERE canal_id = ?", (cid,)).fetchone()), None)
        
        if not canal_id:
            await interaction.response.send_message("⚠️ Todos os canais estão ocupados!", ephemeral=True)
            return
            
        c.execute("UPDATE chaves_leilao SET usos_restantes = usos_restantes - 1 WHERE chave = ?", (str(self.chave),))
        if not interaction.user.guild_permissions.administrator:
            c.execute("INSERT OR REPLACE INTO cooldown_chaves VALUES (?, ?)", 
                     (interaction.user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        
        embed = Embed(title="📝 Formulário de Leilão", color=0x3498db)
        await interaction.response.send_message(embed=embed, 
            view=FormularioLeilaoView(chave_info, canal_id), ephemeral=True)

class FormularioLeilaoView(ui.View):
    def __init__(self, chave_info, canal_id):
        super().__init__()
        self.chave_info = chave_info
        self.canal_id = canal_id
        
    @ui.button(label="Preencher Formulário", style=discord.ButtonStyle.primary)
    async def preencher_form(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(FormularioLeilaoModal(self.chave_info, self.canal_id))

class FormularioLeilaoModal(ui.Modal, title="Formulário de Leilão"):
    def __init__(self, chave_info, canal_id):
        super().__init__()
        self.chave_info = chave_info
        self.canal_id = canal_id
        
    nome_conta = ui.TextInput(label="Nome da Conta")
    jogos = ui.TextInput(label="Jogos", style=discord.TextStyle.long)
    itens = ui.TextInput(label="Itens/Detalhes", style=discord.TextStyle.long)
    preco = ui.TextInput(label="Preço Inicial (R$)")
    
    async def on_submit(self, interaction: Interaction):
        try:
            preco_inicial = float(str(self.preco).replace(',', '.'))
        except ValueError:
            await interaction.response.send_message("❌ Preço inválido!", ephemeral=True)
            return
            
        duracao = self.chave_info[1]
        if 'd' in duracao:
            data_fim = datetime.now() + timedelta(days=int(duracao.split('d')[0]))
        else:
            data_fim = datetime.now() + timedelta(hours=int(duracao.split('h')[0]))
            
        embed = Embed(title="✅ Leilão Pronto", color=0x2ecc71)
        embed.add_field(name="Conta", value=str(self.nome_conta), inline=False)
        embed.add_field(name="Jogos", value=str(self.jogos), inline=False)
        embed.add_field(name="Preço", value=formatar_valor(preco_inicial), inline=True)
        embed.add_field(name="Duração", value=duracao, inline=True)
        
        await interaction.response.send_message(
            embed=embed,
            view=ConfirmarLeilaoView(
                self.chave_info[0],
                str(self.nome_conta),
                str(self.jogos),
                str(self.itens),
                preco_inicial,
                data_fim.strftime("%Y-%m-%d %H:%M:%S"),
                self.canal_id
            ),
            ephemeral=True
        )

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
    async def enviar_leilao(self, interaction: Interaction, button: ui.Button):
        c.execute("""
            INSERT INTO leiloes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.canal_id, interaction.user.id, self.chave, self.nome,
            self.jogos, self.itens, self.preco, self.preco, None, self.data_fim, None
        ))
        conn.commit()
        
        embed = Embed(title=f"🎟️ LEILÃO: {self.nome}", color=0xe67e22)
        embed.description = (
            "🏆 **Como participar?**\n"
            "1. Envie seu lance neste canal (ex: 10.50)\n"
            "2. Lance mínimo: R$ 0,50 acima do atual\n"
            "3. Vencedor será notificado ao final\n\n"
            "📢 **Regras:**\n"
            "• Só lances em números (ex: 10 ou 10.50)\n"
            "• Diferença mínima: R$ 0,50\n"
            "• Sem cancelamento de lances"
        )
        embed.add_field(name="🎮 Jogos", value=self.jogos, inline=False)
        embed.add_field(name="📦 Itens", value=self.itens, inline=False)
        embed.add_field(name="💰 Preço Inicial", value=formatar_valor(self.preco), inline=True)
        embed.add_field(name="⏳ Termina em", value=f"<t:{int(datetime.strptime(self.data_fim, '%Y-%m-%d %H:%M:%S').timestamp())}:R>", inline=True)
        embed.add_field(name="🔢 Maior Lance", value=formatar_valor(self.preco), inline=True)
        embed.add_field(name="👤 Dono", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"ID: {self.chave[:8]}...")
        
        canal = bot.get_channel(self.canal_id)
        view = LeilaoAtivoView(interaction.user.id)
        msg = await canal.send("@everyone 🎉 **NOVO LEILÃO!**", embed=embed, view=view)
        
        c.execute("UPDATE leiloes SET message_id = ? WHERE canal_id = ?", (msg.id, self.canal_id))
        conn.commit()
        
        await auction_system.start_auction(self.canal_id, msg, self.preco, self.data_fim)
        
        # Log de início de leilão
        log_msg = (
            f"🎉 **NOVO LEILÃO INICIADO**\n"
            f"📌 **Conta:** {self.nome}\n"
            f"👤 **Dono:** {interaction.user.mention} (`{interaction.user.id}`)\n"
            f"💰 **Preço inicial:** {formatar_valor(self.preco)}\n"
            f"⏳ **Duração:** {self.chave_info[1]}\n"
            f"🔗 [Ir para o leilão]({msg.jump_url})"
        )
        await enviar_log_leilao(log_msg)
        
        await interaction.response.send_message(f"✅ Leilão criado em {canal.mention}!", ephemeral=True)

class LeilaoAtivoView(ui.View):
    def __init__(self, dono_id):
        super().__init__(timeout=None)
        self.dono_id = dono_id
        
    @ui.button(label="⏱️ Encerrar Leilão", style=discord.ButtonStyle.red, custom_id="encerrar_leilao")
    async def encerrar_leilao(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.dono_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Apenas o dono ou administradores!", ephemeral=True)
            return
            
        await interaction.response.defer()
        await auction_system.finalize_auction(interaction.channel.id, ended_by=interaction.user)
        await interaction.followup.send("⏱️ Leilão encerrado!")

##############################################
## SISTEMA DE LEILÃO
##############################################

class AuctionSystem:
    def __init__(self, bot):
        self.bot = bot
        self.active_auctions = {}
        self.cleanup_tasks = {}
        self.lances_historico = {}  # {channel_id: [{"user": user, "valor": float, "msg_id": int}]}
        
    async def start_auction(self, channel_id, message, preco_inicial, data_fim):
        """Inicia um novo leilão"""
        self.active_auctions[channel_id] = {
            'message': message,
            'current_bid': preco_inicial,
            'current_winner': None,
            'end_time': datetime.strptime(data_fim, "%Y-%m-%d %H:%M:%S"),
            'active': True,
            'lock': asyncio.Lock(),
            'all_messages': [message.id]
        }
        
        self.lances_historico[channel_id] = []
        self.bot.loop.create_task(self._check_auction_end(channel_id))
        
    async def _check_auction_end(self, channel_id):
        """Verifica periodicamente se o leilão acabou"""
        while True:
            auction = self.active_auctions.get(channel_id)
            if not auction or not auction['active']:
                break
                
            if datetime.now() >= auction['end_time']:
                await self.finalize_auction(channel_id)
                break
                
            await asyncio.sleep(1)
            
    async def process_bid(self, message):
        """Processa um novo lance em qualquer mensagem no canal"""
        channel_id = message.channel.id
        auction = self.active_auctions.get(channel_id)
        
        if (not auction or not auction['active'] or 
            message.author.bot or 
            message.id == auction['message'].id):
            return
            
        auction['all_messages'].append(message.id)
            
        async with auction['lock']:
            try:
                bid_amount = float(message.content.replace(',', '.'))
            except ValueError:
                try:
                    await message.delete()
                except:
                    pass
                error_msg = await message.channel.send(
                    f"{message.author.mention} ❌ Formato inválido! Envie apenas números (ex: 10.50)",
                    delete_after=10
                )
                auction['all_messages'].append(error_msg.id)
                return
                
            if bid_amount <= auction['current_bid']:
                try:
                    await message.delete()
                except:
                    pass
                error_msg = await message.channel.send(
                    f"{message.author.mention} ❌ Lance deve ser maior que {formatar_valor(auction['current_bid'])}",
                    delete_after=10
                )
                auction['all_messages'].append(error_msg.id)
                return
                
            if (bid_amount - auction['current_bid']) < 0.5:
                try:
                    await message.delete()
                except:
                    pass
                error_msg = await message.channel.send(
                    f"{message.author.mention} ❌ Diferença mínima de R$0,50. Próximo lance: {formatar_valor(auction['current_bid'] + 0.5)}",
                    delete_after=10
                )
                auction['all_messages'].append(error_msg.id)
                return
                
            # Registra o lance no histórico
            self.lances_historico[channel_id].append({
                "user": message.author,
                "valor": bid_amount,
                "msg_id": message.id,
                "timestamp": datetime.now()
            })

            # Atualiza o maior lance
            auction['current_bid'] = bid_amount
            auction['current_winner'] = message.author
            
            c.execute("""
                UPDATE leiloes 
                SET maior_lance = ?, maior_lance_user = ? 
                WHERE canal_id = ?
            """, (bid_amount, message.author.id, channel_id))
            conn.commit()
            
            await self._update_auction_message(channel_id)
            await message.add_reaction("✅")
            
            # Envia log do lance
            log_msg = (
                f"📌 **NOVO LANCE**\n"
                f"👤 **Usuário:** {message.author.mention} (`{message.author.id}`)\n"
                f"💰 **Valor:** {formatar_valor(bid_amount)}\n"
                f"📅 **Horário:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"🔗 [Mensagem]({message.jump_url})"
            )
            await enviar_log_leilao(log_msg)
            
            notification = await message.channel.send(
                f"🎉 {message.author.mention} ofereceu {formatar_valor(bid_amount)}!",
                delete_after=10
            )
            auction['all_messages'].append(notification.id)
            
    async def _update_auction_message(self, channel_id):
        auction = self.active_auctions.get(channel_id)
        if not auction:
            return
            
        c.execute("""
            SELECT nome_conta, jogos, itens_conta, preco_inicial, maior_lance, maior_lance_user 
            FROM leiloes 
            WHERE canal_id = ?
        """, (channel_id,))
        nome_conta, jogos, itens, preco_inicial, maior_lance, vencedor_id = c.fetchone()
        
        embed = Embed(title=f"🎟️ LEILÃO: {nome_conta}", color=0xe67e22)
        embed.description = (
            "🏆 **Como participar?**\n"
            "1. Envie seu lance neste canal (ex: 10.50)\n"
            "2. Lance mínimo: R$ 0,50 acima do atual\n"
            "3. Vencedor será notificado ao final\n\n"
            "📢 **Regras:**\n"
            "• Só lances em números (ex: 10 ou 10.50)\n"
            "• Diferença mínima: R$ 0,50\n"
            "• Sem cancelamento de lances"
        )
        embed.add_field(name="🎮 Jogos", value=jogos, inline=False)
        embed.add_field(name="📦 Itens", value=itens, inline=False)
        embed.add_field(name="💰 Preço Inicial", value=formatar_valor(preco_inicial), inline=True)
        embed.add_field(name="⏳ Termina em", value=f"<t:{int(auction['end_time'].timestamp())}:R>", inline=True)
        
        if vencedor_id:
            winner = await self.bot.fetch_user(vencedor_id)
            embed.add_field(name="🔢 Maior Lance", 
                          value=f"{formatar_valor(maior_lance)} por {winner.mention}", 
                          inline=True)
        else:
            embed.add_field(name="🔢 Maior Lance", 
                          value=formatar_valor(preco_inicial), 
                          inline=True)
            
        embed.add_field(name="👤 Dono", value=f"<@{auction['message'].author.id}>", inline=True)
        
        await auction['message'].edit(embed=embed)

    async def finalize_auction(self, channel_id, ended_by=None):
        auction = self.active_auctions.get(channel_id)
        if not auction:
            return
            
        auction['active'] = False
        
        c.execute("""
            SELECT nome_conta, jogos, itens_conta, preco_inicial, maior_lance, maior_lance_user, chave 
            FROM leiloes 
            WHERE canal_id = ?
        """, (channel_id,))
        nome_conta, jogos, itens, preco_inicial, maior_lance, vencedor_id, chave = c.fetchone()
        
        embed = Embed(title=f"🏁 LEILÃO ENCERRADO: {nome_conta}", color=0x2ecc71)
        motivo = "Tempo esgotado" if not ended_by else f"Encerrado por {ended_by.mention}"
        embed.add_field(name="📝 Motivo", value=motivo, inline=False)
        
        if vencedor_id:
            embed.add_field(name="🎉 Vencedor", value=f"<@{vencedor_id}> com {formatar_valor(maior_lance)}", inline=False)
            embed.add_field(name="💰 Valor Final", value=formatar_valor(maior_lance), inline=True)
        else:
            embed.add_field(name="ℹ️ Resultado", value="Sem lances válidos", inline=False)
            embed.add_field(name="💰 Preço Inicial", value=formatar_valor(preco_inicial), inline=True)
        
        embed.add_field(name="🎮 Jogos", value=jogos, inline=False)
        embed.add_field(name="📦 Itens", value=itens, inline=False)
        embed.set_footer(text=f"ID: {chave[:8]}... | Encerrado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        canal = self.bot.get_channel(channel_id)
        mensagem_final = await canal.send(embed=embed)
        auction['all_messages'].append(mensagem_final.id)
        
        if auction['message']:
            await auction['message'].edit(content="🔔 LEILÃO ENCERRADO! @everyone", view=None)
        
        # Log de finalização
        log_msg = (
            f"🏁 **LEILÃO FINALIZADO**\n"
            f"📌 **Conta:** {nome_conta}\n"
            f"🏆 **Vencedor:** <@{vencedor_id}> (R$ {maior_lance:.2f})\n"
            f"⏳ **Motivo:** {motivo}\n"
            f"🔗 **ID do Leilão:** `{chave[:8]}...`"
        )
        await enviar_log_leilao(log_msg)
        
        if vencedor_id:
            try:
                user = await self.bot.fetch_user(vencedor_id)
                await user.send(
                    f"🎉 Você venceu o leilão de {nome_conta} por {formatar_valor(maior_lance)}!\n"
                    f"Abra um ticket em <#{CANAL_TICKET_ID}> para finalizar."
                )
            except:
                pass
        
        c.execute("DELETE FROM leiloes WHERE canal_id = ?", (channel_id,))
        conn.commit()
        
        self.cleanup_tasks[channel_id] = self.bot.loop.create_task(
            self._cleanup_channel(channel_id)
        )
        
        if channel_id in self.active_auctions:
            del self.active_auctions[channel_id]
            
    async def _cleanup_channel(self, channel_id):
        await asyncio.sleep(TEMPO_LIMPEZA_LEILAO)
        
        canal = self.bot.get_channel(channel_id)
        if not canal:
            return
            
        try:
            messages = [msg async for msg in canal.history(limit=100)]
            for msg in messages:
                try:
                    await msg.delete()
                except:
                    continue
        except Exception as e:
            print(f"Erro ao limpar canal {channel_id}: {e}")
        
        if channel_id in self.cleanup_tasks:
            del self.cleanup_tasks[channel_id]

# Instancia o sistema de leilão
auction_system = AuctionSystem(bot)

##############################################
## COMANDOS SLASH
##############################################

@bot.tree.command(name="calcular_robux", description="Calcula o valor em reais para Robux")
@app_commands.describe(quantidade="Quantidade de Robux")
async def calcular_robux(interaction: Interaction, quantidade: int):
    await interaction.response.defer()
    
    valor_com, gamepass_com = calcular_valor_robux(quantidade, True)
    valor_sem, gamepass_sem = calcular_valor_robux(quantidade, False)
    
    embed = Embed(title="💰 Cálculo de Robux", color=0x3498db)
    embed.add_field(
        name=f"🔹 {quantidade} Robux com taxa (R$ 0,045 por Robux)",
        value=(
            f"**Valor:** {formatar_valor(valor_com)}\n"
            f"**Preço da Gamepass:** {gamepass_com} Robux\n"
            f"(Para receber {quantidade} Robux após a taxa de 30%)"
        ),
        inline=False
    )
    embed.add_field(
        name=f"🔸 {quantidade} Robux sem taxa (R$ 0,035 por Robux)",
        value=(
            f"**Valor:** {formatar_valor(valor_sem)}\n"
            f"**Preço da Gamepass:** {gamepass_sem} Robux"
        ),
        inline=False
    )
    embed.set_footer(text="Os valores podem variar conforme a cotação atual")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="reservar", description="Faz uma reserva")
@app_commands.describe(nick="Nick do cliente", produto="Produto reservado")
async def reservar(interaction: Interaction, nick: str, produto: str):
    c.execute('INSERT OR REPLACE INTO reservas VALUES (?, ?, ?)',
              (interaction.channel.id, nick, produto))
    conn.commit()

    try:
        await interaction.channel.edit(name="⏳・reservado")
        cargo = interaction.guild.get_role(CARGO_REMOVER_ID)
        if cargo:
            for member in interaction.channel.members:
                await member.add_roles(cargo)
    except:
        pass

    await interaction.response.send_message(
        "✅ Reserva realizada!\nUse `/reserva` para visualizar."
    )

@bot.tree.command(name="reserva", description="Mostra a reserva atual")
async def reserva(interaction: Interaction):
    c.execute('SELECT nick, produto FROM reservas WHERE canal_id = ?', (interaction.channel.id,))
    if reserva := c.fetchone():
        nick, produto = reserva
        cargo = interaction.guild.get_role(CARGO_MENCAO_ID)
        await interaction.response.send_message(
            f"📋 **Reserva Atual**\n**👤 Nick:** {nick}\n**📦 Produto:** {produto}\n"
            f"{cargo.mention if cargo else ''}"
        )
    else:
        await interaction.response.send_message("ℹ️ Nenhuma reserva encontrada.", ephemeral=True)

@bot.tree.command(name="limpar", description="Limpa a reserva atual")
async def limpar(interaction: Interaction):
    c.execute('DELETE FROM reservas WHERE canal_id = ?', (interaction.channel.id,))
    conn.commit()
    await interaction.response.send_message(
        "🧹 Reserva limpa!" if c.rowcount > 0 else "ℹ️ Nada para limpar.",
        ephemeral=True
    )

@bot.tree.command(name="estoque", description="Anuncia novo estoque")
@app_commands.describe(quantidade="Quantidade de Robux")
async def estoque(interaction: Interaction, quantidade: int):
    if interaction.channel.id != CANAL_ESTOQUE_ID:
        await interaction.response.send_message("❌ Use no canal de estoque!", ephemeral=True)
        return
        
    embed = Embed(title="🚀 NOVO ESTOQUE!", color=0x00ff00)
    embed.description = (
        f"**📦 Quantidade:** `{quantidade:,}` Robux\n"
        f"**💳 Melhor custo-benefício!**\n\n"
        f"🔹 **Como comprar?**\n"
        f"1. Abra ticket em <#{CANAL_TICKET_ID}>\n"
        "2. Informe quanto deseja\n"
        "3. Receba em minutos!\n\n"
        "⚠️ **ESTOQUE LIMITADO!**"
    )
    await interaction.response.send_message("@everyone", embed=embed)

@bot.tree.command(name="entregue", description="Marca como entregue")
@app_commands.describe(membro="Membro que recebeu")
async def entregue(interaction: Interaction, membro: discord.Member):
    await interaction.response.defer()
    
    cargo = interaction.guild.get_role(CARGO_ID)
    if not cargo:
        await interaction.followup.send("❌ Cargo não configurado!", ephemeral=True)
        return

    try:
        await interaction.channel.edit(name="✅・entregue")
    except:
        pass

    await interaction.followup.send(
        f"✅ Tudo certo, {membro.mention}?\n"
        f"Avalie em <#{CHANNEL_FEEDBACK_ID}>\n"
        f"{cargo.mention}"
    )

    try:
        await membro.send(embed=Embed(
            title="✅ COMPRA ENTREGUE!",
            description="Sua compra foi entregue! Verifique o ticket para as provas.",
            color=0x00ff00
        ))
    except:
        pass

@bot.tree.command(name="pixinter", description="Mostra PIX internacional")
async def pixinter(interaction: Interaction):
    embed = Embed(title="💳 PIX Internacional", color=0x9b59b6)
    embed.add_field(name="Chave", value="facinlaras0511@gmail.com", inline=False)
    embed.add_field(name="Tipo", value="E-mail", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command(name="pix")
async def pix(ctx):
    embed = Embed(title="💳 PIX", color=0x9b59b6)
    embed.add_field(name="Chave", value="0d8656b8-470e-4e0c-ac22-233ab0aa22ae", inline=False)
    embed.add_field(name="Tipo", value="Aleatória", inline=False)
    await ctx.send(embed=embed)

@bot.tree.command(name="gerarchave", description="Gera chave de leilão (admin)")
@app_commands.describe(duracao="Duração (ex: 1d, 12h)", usos="Número de usos")
@app_commands.checks.has_permissions(administrator=True)
async def gerar_chave_cmd(interaction: Interaction, duracao: str, usos: int):
    chave = gerar_chave()
    c.execute("INSERT INTO chaves_leilao VALUES (?, ?, ?, ?, ?)", 
              (chave, duracao, usos, usos, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    
    embed = Embed(title="🔑 Chave Gerada!", color=0x00ff00)
    embed.add_field(name="Chave", value=f"`{chave}`", inline=False)
    embed.add_field(name="Duração", value=duracao, inline=True)
    embed.add_field(name="Usos", value=str(usos), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="leilao", description="Inicia processo de leilão")
async def leilao(interaction: Interaction):
    embed = Embed(title="🏷️ Sistema de Leilão", color=0x3498db)
    embed.description = (
        "**Como participar?**\n"
        "1. Adquira uma chave com nossos vendedores\n"
        "2. Clique no botão abaixo\n"
        "3. Preencha o formulário\n"
        "4. Seu leilão será publicado!\n\n"
        "⏱️ **Cooldown:** 1 hora entre usos\n\n"
        "**Pacotes:**\n"
        "🕒 12h - R$ 10,00\n"
        "🌞 1 dia - R$ 15,00\n"
        "✨ 3 dias - R$ 25,00\n"
        "🔥 10 dias - R$ 50,00"
    )
    await interaction.response.send_message(embed=embed, view=LeilaoView())

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    
    if message.channel.id in auction_system.active_auctions:
        await auction_system.process_bid(message)

@bot.event
async def on_message_delete(message):
    """Verifica se uma mensagem apagada era um lance válido e restaura o anterior"""
    channel_id = message.channel.id
    
    # Verifica se a mensagem era um lance em um leilão ativo
    if channel_id in auction_system.lances_historico:
        lances = auction_system.lances_historico[channel_id]
        lance_apagado = next((lance for lance in lances if lance["msg_id"] == message.id), None)
        
        if lance_apagado:
            # Remove o lance apagado do histórico
            lances.remove(lance_apagado)
            
            # Pega o último lance válido (se houver)
            if lances:
                ultimo_lance = lances[-1]
                auction = auction_system.active_auctions.get(channel_id)
                
                if auction:
                    # Restaura o lance anterior
                    auction['current_bid'] = ultimo_lance["valor"]
                    auction['current_winner'] = ultimo_lance["user"]
                    
                    c.execute("""
                        UPDATE leiloes 
                        SET maior_lance = ?, maior_lance_user = ? 
                        WHERE canal_id = ?
                    """, (ultimo_lance["valor"], ultimo_lance["user"].id, channel_id))
                    conn.commit()
                    
                    await auction_system._update_auction_message(channel_id)
                    
                    # Envia log de restauração
                    log_msg = (
                        f"❌ **LANCE APAGADO**\n"
                        f"👤 **Usuário:** {message.author.mention} (`{message.author.id}`)\n"
                        f"💸 **Valor removido:** {formatar_valor(lance_apagado['valor'])}\n"
                        f"🔙 **Lance restaurado:** {formatar_valor(ultimo_lance['valor'])} (por {ultimo_lance['user'].mention})\n"
                        f"📅 **Horário:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                    )
                    await enviar_log_leilao(log_msg)

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} online!')
    # Adiciona as views persistentes
    bot.add_view(LeilaoView())
    bot.add_view(LeilaoAtivoView(dono_id=0))
    
    try:
        synced = await bot.tree.sync()
        print(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar: {e}")

bot.run(TOKEN)