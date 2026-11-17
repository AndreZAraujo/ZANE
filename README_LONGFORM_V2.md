# YouTube Dark Channels — Radar Long-form v2

Coletor em **Python 3.10+**, usando exclusivamente a **YouTube Data API v3** e biblioteca padrão. Descobre canais cujos **primeiros vídeos públicos atualmente disponíveis** estão dentro de uma janela de datas, mesmo que a conta tenha sido criada anos antes.

**Missão:** priorizar desempenho de vídeos longos, sem descartar canais que também usam Shorts.

## Critérios padrão

- **5 países:** Estados Unidos (`US`), Canadá (`CA`), Reino Unido (`GB`), Austrália (`AU`), Alemanha (`DE`). Os outros quatro países originais (`NO`, `CH`, `DK`, `NL`) continuam disponíveis por parâmetro.
- **50 canais qualificados por país** como meta, **não garantia**; não há preenchimento fictício de posições.
- **21 dias** corridos até a data da coleta. É possível fixar as datas com `--start` e `--end`.
- Descoberta com 8 famílias de buscas por país, nas faixas de 4–20 minutos e mais de 20 minutos, alternando ordem de publicação e de visualizações.
- Critério de entrada na lista: pelo menos **um vídeo >3 minutos**, com **1.000 views somadas dos vídeos longos da janela**. Ajustável por parâmetro.
- **Canais mistos não são excluídos.** O ranking é calculado com vídeos longos; o desempenho dos vídeos de até 3 minutos não aumenta a pontuação.

## Classificação correta dos formatos

- `ATE_3M_POSSIVEL_SHORT`: vídeo de até 180 s — **formato incerto pela API**. Pode ser Short (quadrado/vertical) ou vídeo horizontal comum.
- `LONG_3A8`: 181–479 s — vídeo tradicional, sem mid-roll por duração.
- `LONG_8A20`: 480–1199 s — vídeo longo, pode ser elegível para anúncios intermediários.
- `LONG_20MAIS`: 1200 s ou mais — vídeo longo estendido.
- `LIVE`: transmissões ao vivo, excluídas da pontuação long-form.
- Após revisão manual, também existem `SHORT_CONFIRMADO` e `LONG_ATE3_VERIFICADO`.

> A API pública de terceiros **não expõe de forma confiável um campo universal `isShort`**, proporção do vídeo original nem audiência geográfica. Portanto o script nunca chama todos os vídeos de até 3 min de Shorts confirmados. `fileDetails` só está disponível ao titular do vídeo. Não é possível inferir o RPM de um canal pelo país declarado.

## Como executar no Windows PowerShell

Coloque `radar_longform_v2.py` na pasta Downloads e garanta que a YouTube Data API v3 esteja habilitada no Google Cloud.

```powershell
cd "$HOME\Downloads"
$env:YOUTUBE_API_KEY = "SUA_CHAVE_AQUI"
python .\radar_longform_v2.py --start 2026-10-27 --end 2026-11-17 --seed-csv ".\resultado_youtube_sem_vidiq\todos_candidatos.csv"
```

**Não compartilhe a chave nem a salve no GitHub.** Se o CSV anterior estiver em outro local, ajuste `--seed-csv` ou omita-o. Para executar a janela móvel de 21 dias, sem datas fixas:

```powershell
python .\radar_longform_v2.py
```

Para mudar as condições:

```powershell
python .\radar_longform_v2.py --countries US,GB,DE,NO,CH --target 50 --min-long-uploads 2 --min-long-views 3000
```

Para ampliar os temas, crie `temas.json` com listas de termos por país e execute com `--queries-file temas.json --terms-per-country 10 --max-search-requests 100` **somente se ainda houver cota de buscas disponível**.

## Saídas (`resultado_longform_v2/`)

| Arquivo | Uso |
|---|---|
| `top50_longform_por_pais.csv` | Ranking final por país, com pontuação, médias, medianas, proporções e links |
| `canais_elegiveis_analisados.csv` | Todos os canais que passaram pela verificação da primeira publicação, inclusive Shorts-only não qualificados |
| `videos_detalhados.csv` | Cada vídeo público da janela, com duração, views, likes, links e views/dia |
| `resumo_paises.csv` | Candidatos descobertos, elegíveis, qualificados e posições pendentes |
| `auditoria_busca.csv` | Cada consulta realizada e o volume de resultados |
| `auditoria_candidatos.csv` | Motivos para excluir / manter cada canal |
| `revisao_short_manual.csv` | Revisar vídeos de até 3 min e informar `SHORT` ou `LONG` |
| `historico_snapshots.csv` | Fotografia diária de estatísticas públicas, para calcular crescimento futuro |
| `crescimento_monitorado.csv` | Diferenças de inscritos/views entre datas realmente observadas |
| `metodologia.json` | Datas, parâmetros, cota consumida e advertências |

### Conferir vídeos curtos manualmente

Abra `revisao_short_manual.csv`. Na coluna `tipo_confirmado`, informe `SHORT` ou `LONG` após verificar o vídeo no YouTube. Na próxima execução, mantenha o arquivo no mesmo local e use:

```powershell
python .\radar_longform_v2.py --manual-csv ".\resultado_longform_v2\revisao_short_manual.csv"
```

O script preserva as classificações já preenchidas. Se for analisar a janela original, repita também os parâmetros `--start` e `--end` usados antes.

### Compreender o ranking

O *score* é um indicador **interno e heurístico**, construído com logs de mediana de views longas, total de views longas, mediana de views/dia, quantidade de vídeos longos e quantidade de vídeos de 8+ min. **Não mede RPM, receita nem recomendações do algoritmo do YouTube**. Canais com país declarado correspondente à busca vêm primeiro; os encontrados somente por `regionCode` ficam sinalizados como não verificados.

A média e a mediana são calculadas sobre visualizações públicas atuais de vídeos publicados na janela, **não sobre o aumento diário retroativo**. O crescimento real de inscritos/views exige várias execuções; o script importa os snapshots das coletas anteriores quando o CSV original é fornecido e mantém canais monitorados mesmo depois que deixam a janela móvel.

## Consumo de cota

A documentação atual da API descreve **100 chamadas `search.list` por dia** na quota de pesquisas e **10.000 unidades por dia para outros métodos** no projeto padrão. O script utiliza até 80 buscas e até 6.000 consultas de outros endpoints por execução, conforme limites locais configuráveis. **Não são garantias de cota remanescente na sua conta.** Consultas inválidas também podem contar.

Referências: [search.list](https://developers.google.com/youtube/v3/docs/search/list), [videos](https://developers.google.com/youtube/v3/docs/videos), [política de Shorts](https://support.google.com/youtube/answer/15424877?hl=pt-BR), [cota da API](https://developers.google.com/youtube/data/determine_quota_cost).

## Testes

No diretório que contém o script:

```powershell
python -m unittest -v test_radar_longform_v2.py
```

Os testes utilizam respostas simuladas: **não exigem chave da API nem gastam cota**. Ainda é necessário executar uma coleta real para verificar os resultados das buscas e a cota disponível na sua conta.