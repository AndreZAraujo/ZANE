# YouTube Dark Channels — Radar de Novos Canais

Coletor em Python que usa a **YouTube Data API v3** para descobrir canais em nove países e filtrar aqueles cujo **primeiro vídeo público disponível** foi publicado dentro de uma janela configurável.

> **Status:** protótipo de pesquisa. A busca é **amostral**, não um ranking completo do YouTube. O primeiro vídeo público disponível pode não ser o primeiro vídeo já publicado (por exemplo, se vídeos antigos foram apagados ou tornados privados).

## Mercados pesquisados

Estados Unidos (US), Austrália (AU), Noruega (NO), Suíça (CH), Canadá (CA), Reino Unido (GB), Dinamarca (DK), Alemanha (DE) e Países Baixos (NL).

## Pré-requisitos

- Python 3.10 ou superior (somente biblioteca padrão).
- Uma chave da [YouTube Data API v3](https://developers.google.com/youtube/v3/getting-started), habilitada em um projeto Google Cloud.
- Cota disponível na API.

## Como executar

**Windows PowerShell:**

```powershell
$env:YOUTUBE_API_KEY = "SUA_CHAVE"
python .\coletor_youtube_primeira_publicacao.py
```

**Linux/macOS:**

```bash
export YOUTUBE_API_KEY="SUA_CHAVE"
python3 coletor_youtube_primeira_publicacao.py
```

**Não coloque sua chave no código nem a publique no GitHub.** Use variáveis de ambiente. Evite gravar a chave no histórico do terminal se isso for uma preocupação no seu ambiente.

## Configuração do período

Edite as constantes `WINDOW_START` e `WINDOW_END_EXCLUSIVE` no arquivo Python. No protótipo, a janela é **27/10/2026 a 17/11/2026**, inclusive (fim exclusivo em 18/11/2026 UTC).

## Saídas

O programa gera a pasta `resultado_youtube_sem_vidiq/` com:

- `todos_candidatos.csv`: canais encontrados, país declarado, número de inscritos, views acumuladas e situação de elegibilidade do primeiro upload público.
- `rankings_9_paises.csv`: até 10 canais por país ordenados por inscritos atuais e até 10 por views dos vídeos publicados na janela, **somente dentro da amostra descoberta**.

## Limitações importantes

1. **Descoberta não exaustiva.** `search.list` pesquisa vídeos por termos predefinidos, não descobre todos os canais novos do YouTube. Os termos privilegiam história, economia e negócios.
2. **País do canal ≠ país dos espectadores.** O filtro usa o país público declarado do canal, e não a localização da audiência. Isso não verifica RPM.
3. **Inscritos atuais ≠ inscritos ganhos no período.** Para medir crescimento real, execute coletas sucessivas e guarde snapshots.
4. **Views dos vídeos na janela não são views ganhas exclusivamente na janela.** São visualizações atuais dos vídeos publicados nesse período.
5. **Primeiro upload público conhecido ≠ primeiro upload histórico garantido.** Vídeos privados, não listados ou removidos podem alterar a conclusão.
6. Consultas a `search.list` consomem cota da API; acompanhe o uso no Google Cloud.

## Arquivo principal

[`coletor_youtube_primeira_publicacao.py`](./coletor_youtube_primeira_publicacao.py)

Projeto experimental, desenvolvido para análise de oportunidades de conteúdo no YouTube.
