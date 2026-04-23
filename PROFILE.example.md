# Research Vault — PROFILE template

> Copy this file to `PROFILE.md` (gitignored) and fill in the details
> about your own environment. No skill reads `PROFILE.md` at runtime —
> it is purely a reference card for agents that chat with you about
> workstation / server setup. All values actually consumed by skills
> live in `.secrets/` and `.localconfig/` (see `SECRETS.md`).

---

## About Me

- **Identity**: <e.g. PhD student, research scientist, hobbyist>
- **Research field**: <e.g. Deep Learning, ML systems, NLP>
- **Specific areas**: <bullet list of sub-areas>
- **Goal**: <one-line research goal or workflow objective>

---

## Devices

### Local — <e.g. MacBook Air (M1, 2020)>

> Purpose: <e.g. literature review, paper writing, SSH gateway>

**Ownership & admin**: <owner or lab-issued; admin privileges yes/no>

| Item    | Detail |
| ------- | ------ |
| Model   | <model string> |
| Chip    | <CPU/SoC> |
| Memory  | <N GB> |
| Storage | <N GB> |
| OS      | <OS + build> |
| User    | `<local-user>` |
| Shell   | <shell> |

### Remote — <GPU server or cloud>

> Purpose: <training / experiments / fine-tuning>

**SSH** (operational values live in `.localconfig/server.env`):
```
host alias  : <set via RESMAX_SSH_HOST>
working dir : <set via RESMAX_SSH_REMOTE_DIR>
conda env   : <set via RESMAX_SSH_CONDA_ENV>
```

**Ownership & admin**: <shared lab server / personal cloud; sudo yes/no>

| Item | Detail |
| ---- | ------ |
| Hostname | <hostname> |
| OS | <OS + kernel> |
| CPU | <sockets x cores x threads> |
| Memory | <N GB> |
| GPU | <N x model, VRAM> |
| GPU Driver | <driver version> |
| CUDA Toolkit | <cuda version> |

**Conda environments**:

| Env | Python | PyTorch | CUDA (torch) | Notable packages |
| --- | ------ | ------- | ------------ | ---------------- |
| `<env>` | — | — | — | — |

---

## Agent Usage Notes

- **Language preference**: <e.g. Chinese for chat, English for code comments>
- **Workflow philosophy**: <first-principles / pragmatic / research-first ...>
- **Privilege split**: <where you have sudo vs. where you don't>

## Credentials

Credentials never appear in this file. All API keys, passwords, and
personal contact emails live in `.secrets/` (gitignored). Machine-
specific runtime config lives in `.localconfig/`. See `SECRETS.md` at
the repo root for the authoritative list and the supplement protocol.
