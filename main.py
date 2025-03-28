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
TEMPO_LIMPEZA_LEILAO = 5 * 60  # 5 minutos em segundos

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

##############################################
## SISTEMA DE LEILÃO ATUALIZADO
##############################################

class AuctionSystem:
    def __init__(self, bot):
        self.bot = bot
        self.active_auctions = {}
        self.cleanup_tasks = {}
        
    async def start_auction(self, channel_id, message, preco_inicial, data_fim):
        """Inicia um novo leilão"""
        self.active_auctions[channel_id] = {
            'message': message,
            'current_bid': preco_inicial,
            'current_winner': None,
            'end_time': datetime.strptime(data_fim, "%Y-%m-%d %H:%M:%S"),
            'active': True,
            'lock': asyncio.Lock(),
            'all_messages': [message.id]  # Armazena todas as mensagens do leilão
        }
        
        # Inicia a tarefa de verificação
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
        
        # Verificações básicas
        if (not auction or not auction['active'] or 
            message.author.bot or 
            message.id == auction['message'].id):
            return
            
        # Adiciona mensagem à lista para limpeza posterior
        auction['all_messages'].append(message.id)
            
        async with auction['lock']:
            try:
                bid_amount = float(message.content.replace(',', '.'))
            except ValueError:
                # Mensagem apenas visível para quem enviou
                error_msg = await message.reply(
                    "❌ Formato inválido! Envie apenas números (ex: 10.50)", 
                    ephemeral=True
                )
                auction['all_messages'].append(error_msg.id)
                return
                
            # Valida o lance
            if bid_amount <= auction['current_bid']:
                error_msg = await message.reply(
                    f"❌ Lance deve ser maior que {formatar_valor(auction['current_bid'])}", 
                    ephemeral=True
                )
                auction['all_messages'].append(error_msg.id)
                return
                
            if (bid_amount - auction['current_bid']) < 0.5:
                error_msg = await message.reply(
                    f"❌ Diferença mínima de R$0,50. Próximo lance: {formatar_valor(auction['current_bid'] + 0.5)}", 
                    ephemeral=True
                )
                auction['all_messages'].append(error_msg.id)
                return
                
            # Atualiza o lance
            auction['current_bid'] = bid_amount
            auction['current_winner'] = message.author
            
            # Atualiza no banco de dados
            c.execute("""
                UPDATE leiloes 
                SET maior_lance = ?, maior_lance_user = ? 
                WHERE canal_id = ?
            """, (bid_amount, message.author.id, channel_id))
            conn.commit()
            
            # Atualiza a mensagem e envia confirmação
            await self._update_auction_message(channel_id)
            await message.add_reaction("✅")
            notification = await message.channel.send(
                f"🎉 {message.author.mention} ofereceu {formatar_valor(bid_amount)}!",
                delete_after=10
            )
            auction['all_messages'].append(notification.id)
            
    async def _update_auction_message(self, channel_id):
        """Atualiza a mensagem do leilão com o novo lance"""
        auction = self.active_auctions.get(channel_id)
        if not auction:
            return
            
        embed = auction['message'].embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "🔢 Maior Lance Atual":
                embed.set_field_at(i, 
                    name="🔢 Maior Lance Atual", 
                    value=f"{formatar_valor(auction['current_bid'])} por {auction['current_winner'].mention}"
                )
        
        await auction['message'].edit(embed=embed)
        
    async def finalize_auction(self, channel_id, ended_by=None):
        """Finaliza o leilão e agenda limpeza"""
        auction = self.active_auctions.get(channel_id)
        if not auction:
            return
            
        auction['active'] = False
        
        # Obtém dados do banco de dados
        c.execute("""
            SELECT nome_conta, jogos, itens_conta, preco_inicial, maior_lance, maior_lance_user, chave 
            FROM leiloes 
            WHERE canal_id = ?
        """, (channel_id,))
        nome_conta, jogos, itens, preco_inicial, maior_lance, vencedor_id, chave = c.fetchone()
        
        # Cria embed de encerramento
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
        
        # Envia mensagem de encerramento
        canal = self.bot.get_channel(channel_id)
        mensagem_final = await canal.send(embed=embed)
        auction['all_messages'].append(mensagem_final.id)
        
        # Edita a mensagem original
        if auction['message']:
            await auction['message'].edit(content="🔔 LEILÃO ENCERRADO! @everyone", view=None)
        
        # Notifica o vencedor
        if vencedor_id:
            try:
                user = await self.bot.fetch_user(vencedor_id)
                await user.send(
                    f"🎉 Você venceu o leilão de {nome_conta} por {formatar_valor(maior_lance)}!\n"
                    f"Abra um ticket em <#{CANAL_TICKET_ID}> para finalizar."
                )
            except:
                pass
        
        # Limpa o leilão no banco de dados
        c.execute("DELETE FROM leiloes WHERE canal_id = ?", (channel_id,))
        conn.commit()
        
        # Agenda limpeza do canal após 5 minutos
        self.cleanup_tasks[channel_id] = self.bot.loop.create_task(
            self._cleanup_channel(channel_id)
        )
        
        # Remove o leilão ativo
        if channel_id in self.active_auctions:
            del self.active_auctions[channel_id]
            
    async def _cleanup_channel(self, channel_id):
        """Limpa todas as mensagens do leilão após 5 minutos"""
        await asyncio.sleep(TEMPO_LIMPEZA_LEILAO)
        
        canal = self.bot.get_channel(channel_id)
        if not canal:
            return
            
        # Obtém as últimas 100 mensagens para limpar mesmo se houver muitas
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

# ... (o restante do código com as classes de view permanece igual)

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    
    # Verifica se a mensagem está em um canal de leilão ativo
    if message.channel.id in auction_system.active_auctions:
        await auction_system.process_bid(message)

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} online!')
    bot.add_view(LeilaoView())
    bot.add_view(LeilaoAtivoView(dono_id=0))
    
    try:
        synced = await bot.tree.sync()
        print(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar: {e}")

bot.run(TOKEN)