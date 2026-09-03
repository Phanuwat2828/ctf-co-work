FROM kalilinux/kali-rolling:latest

ARG DEBIAN_FRONTEND=noninteractive

# ctf        = ชุดใหญ่สำหรับ CTF
# everything = ลง kali-linux-everything ทั้งหมด
ARG TOOLSET=ctf

ENV TERM=xterm-256color \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin

# =========================================================
# Base utilities
# =========================================================
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        git \
        gnupg \
        sudo \
        locales \
        bash \
        zsh \
        tmux \
        vim \
        nano \
        less \
        man-db \
        jq \
        tree \
        file \
        unzip \
        zip \
        p7zip-full \
        tar \
        gzip \
        bzip2 \
        xz-utils \
        rsync \
        openssh-client \
        netcat-openbsd \
        socat \
        rlwrap \
        screen \
        procps \
        lsof \
        strace \
        ltrace \
        make \
        gcc \
        g++ \
        build-essential \
        cmake \
        pkg-config \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        pipx \
        ruby \
        ruby-dev \
        golang-go \
        default-jdk \
        dnsutils \
        iproute2 \
        iputils-ping \
        traceroute \
        tcpdump \
        tshark \
        openvpn \
        wireguard-tools \
        proxychains4 \
        tor \
        fzf \
        ripgrep \
        fd-find \
        bat && \
    rm -rf /var/lib/apt/lists/*


# =========================================================
# Kali CTF Toolsets
# =========================================================
RUN apt-get update && \
    if [ "$TOOLSET" = "everything" ]; then \
        echo "[+] Installing kali-linux-everything..." && \
        apt-get install -y kali-linux-everything; \
    else \
        echo "[+] Installing CTF toolsets..." && \
        apt-get install -y \
            kali-linux-headless \
            kali-tools-information-gathering \
            kali-tools-vulnerability \
            kali-tools-web \
            kali-tools-database \
            kali-tools-passwords \
            kali-tools-reverse-engineering \
            kali-tools-exploitation \
            kali-tools-sniffing-spoofing \
            kali-tools-post-exploitation \
            kali-tools-forensics; \
    fi && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# =========================================================
# Extra CTF packages
# =========================================================
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gdb \
        gdb-multiarch \
        checksec \
        python3-pwntools \
        ropgadget \
        nasm \
        binutils \
        binwalk \
        patchelf \
        elfutils \
        radare2 \
        apktool \
        nmap \
        masscan \
        sqlmap \
        nikto \
        gobuster \
        ffuf \
        feroxbuster \
        dirsearch \
        wfuzz \
        hydra \
        john \
        hashcat \
        crunch \
        cewl \
        wordlists \
        seclists \
        aircrack-ng \
        bettercap \
        mitmproxy \
        metasploit-framework \
        exploitdb \
        steghide \
        foremost \
        scalpel \
        exiftool \
        sleuthkit \
        testdisk \
        foremost \
        sqlite3 \
        redis-tools \
        postgresql-client \
        mariadb-client \
        smbclient \
        ldap-utils \
        snmp \
        onesixtyone \
        enum4linux \
        impacket-scripts && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# =========================================================
# Ruby CTF tools
# =========================================================
RUN gem install one_gadget --no-document || true


# =========================================================
# Python environment
# =========================================================
RUN python3 -m venv /opt/ctf-venv

ENV PATH="/opt/ctf-venv/bin:${PATH}"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
        pwntools \
        ropper \
        capstone \
        unicorn \
        keystone-engine \
        requests \
        beautifulsoup4 \
        lxml \
        pycryptodome \
        cryptography \
        z3-solver \
        sympy \
        numpy \
        pillow \
        ipython \
        flask \
        fastapi \
        uvicorn


# =========================================================
# Wordlists
# =========================================================
RUN if [ -f /usr/share/wordlists/rockyou.txt.gz ]; then \
        gunzip -kf /usr/share/wordlists/rockyou.txt.gz; \
    fi


# =========================================================
# Workspace
# =========================================================
RUN mkdir -p \
        /work \
        /loot \
        /tools \
        /root/.config \
        /root/.cache


# =========================================================
# Shell aliases
# =========================================================
RUN printf '%s\n' \
    'export TERM=xterm-256color' \
    'export EDITOR=vim' \
    'alias ll="ls -lah --color=auto"' \
    'alias la="ls -A --color=auto"' \
    'alias ..="cd .."' \
    'alias ...="cd ../.."' \
    'alias grep="grep --color=auto"' \
    'alias ports="ss -tulpn"' \
    'alias myip="ip addr"' \
    'alias serve="python3 -m http.server"' \
    'alias pwn="python3"' \
    'alias updatekali="apt update && apt full-upgrade -y"' \
    >> /root/.zshrc


WORKDIR /work

SHELL ["/bin/bash", "-c"]

CMD ["sleep", "infinity"]
