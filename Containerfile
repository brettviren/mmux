FROM debian:bookworm-slim

# BUN_INSTALL=/usr/local makes bun and its global packages land in /usr/local/bin
ENV BUN_INSTALL=/usr/local
ENV PATH="/usr/local/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git bash unzip sudo \
    && rm -rf /var/lib/apt/lists/*

# bun (JS runtime / package manager) — installed to /usr/local/bin/bun
RUN curl -fsSL https://bun.sh/install | bash

# Claude Code CLI — global install lands in /usr/local/bin/claude (via BUN_INSTALL)
RUN bun install -g @anthropic-ai/claude-code

# uv (Python package manager) — installed to /usr/local/bin/uv
RUN curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

# beads issue tracker (bd) — install via mise then copy binary to /usr/local/bin
RUN curl -fsSL https://mise.run | MISE_INSTALL_PATH=/usr/local/bin/mise sh \
 && MISE_DATA_DIR=/opt/mise mise install --yes 'github:gastownhall/beads@latest' \
 && find /opt/mise/installs -maxdepth 3 -name "bd" -perm /111 -type f | head -1 \
    | xargs -I{} install -m755 {} /usr/local/bin/bd

# Unprivileged user with passwordless sudo
RUN useradd -m -s /bin/bash user \
 && echo "user ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER user
WORKDIR /workspace
CMD ["claude", "--dangerously-skip-permissions"]
