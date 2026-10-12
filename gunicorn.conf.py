# Configuracao do servidor (o gunicorn le este arquivo sozinho ao iniciar).
# Varias threads: a IA do chat pode levar dezenas de segundos consultando o
# sistema, e os paineis dos gestores (que consultam a cada 5s) nao podem travar.
workers = 2
worker_class = 'gthread'
threads = 8
timeout = 150
