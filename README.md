# Research Vault

> This Obsidian vault serves as the central workspace for all research activities, managed collaboratively with AI agents (Cursor, Claude Code, etc.). It covers literature review, experiment logging, paper writing, and more.

---

## About Me

- **Identity**: PhD student (2nd year), School of Computer Science and Technology, a 985 university in mainland China
- **Research field**: Deep Learning
- **Specific areas**:
  - Computer Vision
  - 4D Gaussian Splatting
  - Large Language Models (LLM)
  - Vision-Language Models (VLM)
  - Explainability / Interpretability
  - AI for Science — X-ray crystallography at high-energy light sources
- **Goal**: Leverage AI agents to boost efficiency across the entire research pipeline, eliminating dirty work in every stage

---

## Devices

### Local — MacBook Air (current machine)

> All non-GPU tasks: literature review, paper writing, note-taking, SSH to remote servers.

**Ownership & admin**: Personally owned machine. You have full administrator control (install/update tools system-wide via Homebrew, change macOS settings, manage disks and backups, etc.). Agents may assume permissive local setup unless you say otherwise.

| Item    | Detail                                  |
| ------- | --------------------------------------- |
| Model   | MacBook Air (M1, 2020) — MacBookAir10,1 |
| Chip    | Apple M1 (8-core: 4P + 4E)              |
| Memory  | 8 GB                                    |
| Storage | 245 GB APFS (≈ 13 GB free)              |
| OS      | macOS 26.3 (Build 25D125), arm64        |
| User    | `zhangzhao`                             |
| Shell   | zsh                                     |


**Key software**:


| Tool     | Version                            |
| -------- | ---------------------------------- |
| Python   | 3.13.0                             |
| Conda    | 24.11.0                            |
| Git      | 2.50.1 (Apple Git)                 |
| Node.js  | 25.9.0                             |
| Homebrew | 5.1.5                              |
| LaTeX    | TeX Live 2024 (pdfTeX 3.141592653) |
| SSH      | OpenSSH 10.2p1                     |
| Docker   | not installed                      |


### Remote — GPU Server (4 × RTX 5090, Ubuntu)

> Algorithm development, model training, experiment execution. Connected via SSH from MacBook.

**SSH config**: `ssh 5090` → `zz@172.23.148.136:49281`

**Ownership & admin**: Lab / shared GPU server. Account `zz` is a **normal user without `sudo` / administrator** privileges. System packages, drivers, and OS-level changes need lab IT or a privileged account. Agents should default to **user-scoped** tooling (conda/miniconda, venv, pip/uv in project or home) and writable paths under `$HOME` or lab-approved locations on `/data`; do not assume `apt install` without confirmation.

| Item         | Detail                                                                           |
| ------------ | -------------------------------------------------------------------------------- |
| Hostname     | user-SY8108G-D12R-G4                                                             |
| OS           | Ubuntu 22.04.5 LTS, kernel 6.8.0-90-generic                                      |
| CPU          | 2 × Intel Xeon Silver 4410Y (48 threads total: 2 sockets × 12 cores × 2 threads) |
| Memory       | 128 GB DDR                                                                       |
| GPU          | 4 × NVIDIA GeForce RTX 5090 (32 GB VRAM each, 128 GB total)                      |
| GPU Driver   | 580.95.05                                                                        |
| CUDA Toolkit | 12.8                                                                             |
| System disk  | 1.8 TB (≈ 614 GB free) mounted at `/`                                            |
| Data disk    | 7.3 TB (≈ 5.4 TB free) mounted at `/data`                                        |
| Home usage   | ~70 GB in `/home/zz`                                                             |
| User         | `zz`                                                                             |
| Git          | 2.34.1                                                                           |
| Docker       | not installed                                                                    |


**Conda environments** (miniconda3 + miniforge3):


| Env    | Python | PyTorch      | CUDA (torch) | Notable packages |
| ------ | ------ | ------------ | ------------ | ---------------- |
| `llm`  | —      | 2.10.0+cu128 | 12.8         | —                |
| `vllm` | —      | 2.10.0+cu128 | 12.8         | vLLM 0.19.0      |

### Privileges — implications for agents

| Context | Admin? | Typical decisions |
| ------- | ------ | ----------------- |
| MacBook | Yes (owner) | OK to suggest Homebrew, global CLIs, Docker if you add it later, iCloud paths, full disk access where needed. |
| `5090` server | No | Prefer conda envs / project-local installs; document exact paths; large artifacts on `/data` if permitted; open tickets or ask lab for system CUDA/driver bumps. |

---

## Vault Structure

> TODO: Define and document the folder structure as the vault grows.

---

## Agent Usage Notes

- **Language preference**: Chinese for communication, English for code and comments
- **Obsidian vault path**: `/Users/zhangzhao/Library/Mobile Documents/iCloud~md~obsidian/Documents`
- **Privilege split**: Local Mac = full control; remote `5090` = non-admin — scope commands and file layouts accordingly (see **Privileges — implications for agents** above).
- **Workflow philosophy**: First-principles thinking — challenge assumptions, avoid path dependency, suggest shorter/cheaper alternatives when applicable

