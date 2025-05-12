# Use a imagem oficial do n8n como base
FROM n8nio/n8n 

# Mudar para usuário root para permitir instalações
USER root

# Instalar Python e criar ambiente virtual (mantido, pode ser útil para outros nós Code)
RUN apk add --no-cache python3 py3-pip && \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir PyMuPDF

# --- Instalar o Cliente Docker CLI ---
# Adicionar o repositório oficial do Docker e instalar o cliente
RUN apk add --no-cache docker

# --- Ajustar PATH (mantido do último ajuste) ---
# Adiciona o diretório bin do ambiente virtual ao início do PATH
# Preserva o PATH original da imagem base usando ${PATH}
ENV PATH="/opt/venv/bin:${PATH}"
# ------------------------------------------

# Retornar ao usuário padrão do n8n
USER node

# O comando padrão do n8n (CMD ["tini", "--", "n8n"]) já está definido na imagem base.
# Não precisamos redefini-lo aqui.
