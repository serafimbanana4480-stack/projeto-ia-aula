# Minimal sandbox image used by backend/tools/code_executor.py (§11.2).
# - No network
# - Read-only filesystem
# - Multi-language runtimes
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip \
      nodejs npm \
      bash \
      ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Debian already ships user `nobody` (UID 65534, GID 65534). No need to create it.
USER nobody
WORKDIR /tmp
CMD ["bash"]
