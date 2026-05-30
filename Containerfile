FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
   autoconf bash build-essential ca-certificates clang coreutils curl direnv emacs \
   fd-find gfortran git gpg jq less llvm locales lsb-release man-db \
   python-is-python3 python3 \
   python3-click python3-setuptools python3-venv python3-yaml ripgrep sudo \
   unzip wget zip zlib1g-dev \
   && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

# This should install into /usr/local/bin if writable.
RUN curl -fsSL https://raw.githubusercontent.com/gastownhall/beads/main/scripts/install.sh | bash

RUN set -e \
   && VERSION=$(curl -fsSL https://downloads.claude.ai/claude-code-releases/latest) \
   && PLATFORM=linux-x64 \
   && curl -fsSL -o /usr/local/bin/claude \
      "https://downloads.claude.ai/claude-code-releases/$VERSION/$PLATFORM/claude" \
   && chmod +x /usr/local/bin/claude


# claude won't --dangerously-skip-permissions running as root so we make a user.
# Unprivileged user with passwordless sudo.
RUN useradd -m -s /bin/bash user \
 && echo "user ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER user

ENV PATH="/home/user/.local/bin:${PATH}"
# RUN curl -fsSL https://claude.ai/install.sh | bash

WORKDIR /workspace
CMD ["claude", "--dangerously-skip-permissions"]
