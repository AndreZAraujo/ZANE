# Dark Channels Radar v3.1 — SEM FILTRO POR TEMA (correção da cota)

**Objetivo:** descobrir canais com primeira publicação pública conhecida recente e mensurar **long-form** de qualquer assunto nos Estados Unidos, Canadá, Reino Unido, Austrália e Alemanha. Canais mistos continuam elegíveis. O nicho será **resultado da análise**, nunca uma condição da pesquisa.

> **Atualização v3.1 (17/11/2026):** corrigimos o tratamento de erro HTTP 429 quando a mensagem do Google indica `Search Queries per day`. Em vez de continuar 80 tentativas inúteis, o programa encerra imediatamente, grava `status_coleta.json` e `auditoria_busca_parcial_quota.csv`, e **preserva rankings antigos**. Nenhuma mudança na seleção de nichos.

> A busca é uma **amostra da API pública**, não um censo do YouTube nem uma confirmação de RPM. `regionCode` significa disponibilidade regional do vídeo; **não identifica residência do canal nem a localização dos espectadores**. O país declarado pode ser diferente do país da busca. A API não permite identificar automaticamente todos os Shorts em canais de terceiros.

## O que mudou em relação à v2

| Dimensão | v2 | v3 |
| --- | --- | --- |
| Descoberta | Oito termos por idioma, como `business documentary` e `money explained` | **Nenhuma palavra-chave:** `search.list` **sem `q`**, `topicId` ou `videoCategoryId` |
| Diversidade | Predomínio de finanças, negócios, história e tecnologia | Qualquer tema que aparecer na amostra de vídeos |
| Estratégia | `q` + formato + região | Fatias temporais + região + duração + ordenação por data/views |
| Geografia | Descartava canais com país declarado diferente | Mantém; registra correspondência e **não finge conhecer audiência** |
| Nicho | Implícito pela pesquisa | Categorias públicas calculadas **somente após** coletar os vídeos |
| Rankings | Score long-form | Score + rankings independentes por views, mediana e velocidade |
| Shorts | Até 180s incertos; confirmação manual | Igual, preservando confirmações anteriores automaticamente |
| Histórico | Snapshots de canais | Mantidos; permite importar histórico da v2 com `--history-source` |

## Instalação

Python **3.10+**, apenas biblioteca padrão. É necessária uma chave válida da [YouTube Data API v3](https://developers.google.com/youtube/data/getting-started). **Nunca publique ou envie a chave.**

### Windows PowerShell — sem configurar variáveis de ambiente

1. Coloque **`radar_sem_nicho_v3.py`** e **`youtube_api_key.txt`** **na mesma pasta**. O pacote original incluía um TXT-modelo; o ZIP de correção v3.1 inclui apenas o exemplo sem segredo. Preserve seu `youtube_api_key.txt` já preenchido.
2. Abra `youtube_api_key.txt` no Bloco de Notas. **Substitua `COLE_SUA_CHAVE_AQUI` por sua chave real**, em uma única linha, sem aspas, e salve (`Ctrl+S`). Não altere a extensão para `.txt.txt`.
3. Execute o script:

```powershell
cd "C:\Users\andre\Desktop\radar_longform_v2_codigo_e_testes"

# Conferir a grade de consultas sem gastar cota:
python .\radar_sem_nicho_v3.py --plan-only

# Pesquisa sem restrição de temas (últimos 21 dias, 5 regiões, até 50 canais por região)
python .\radar_sem_nicho_v3.py --history-source ".\resultado_longform_v2\historico_snapshots.csv"
```

**A chave é lida automaticamente do arquivo TXT ao lado do script**, não importa de qual pasta você abriu o PowerShell. O arquivo **não será enviado ao GitHub**: `youtube_api_key.txt` está no `.gitignore`. Não compartilhe o TXT depois de preenchê-lo e não envie um ZIP contendo a sua chave.

O repositório público contém apenas `youtube_api_key.example.txt` (sem segredo); se você baixar os arquivos diretamente do GitHub, copie ou renomeie esse exemplo para `youtube_api_key.txt` antes de preencher.

A variável de ambiente `YOUTUBE_API_KEY` continua funcionando como alternativa. Se os dois existirem, **o TXT preenchido tem prioridade**. Não é necessário reinstalar Python nem recriar a credencial no Google Cloud.

Para repetir **a janela original**:

```powershell
python .\radar_sem_nicho_v3.py --start 2026-10-28 --end 2026-11-17
```

Para preservar o histórico de crescimento coletado com a v2, **sem importar o viés temático dos candidatos antigos**:

```powershell
python .\radar_sem_nicho_v3.py --history-source ".\resultado_longform_v2\historico_snapshots.csv"
```

> **Recomendado:** comece **sem `--seed-csv`**; isso mantém a nova descoberta sem herdar a amostra enviesada da v2. A opção `--history-source` importa apenas dados históricos, sem alimentar a busca por canais. Se quiser *deliberadamente* revisar os candidatos antigos, execute outra rodada com `--seed-csv` e interprete a amostra como híbrida.

## Como a busca funciona

A busca original de 21 dias é dividida em 4 intervalos temporais por país. Para cada intervalo há 4 consultas: vídeos `medium` (de 4 a 20 minutos) e `long` (mais de 20 minutos), ordenados por `date` e `viewCount`. Isso totaliza **80 buscas com os 5 países padrão**. A API retorna no máximo 50 vídeos por página; as consultas são **amostrais**. Nenhuma delas recebe `q`, categoria ou tópico. **A ausência de um assunto nos resultados não significa que não exista demanda.**

O parametro `safeSearch=none` tambem evita a filtragem tematica implicita do valor padrao (sujeito a restricoes do YouTube e da regiao).

A partir dos canais encontrados, o código percorre a playlist pública de uploads para avaliar a data do vídeo mais antigo ainda público. Um canal criado em 2018, mas cujo vídeo público mais antigo é de outubro de 2026, pode entrar. Se existe um vídeo público antigo, não entra; vídeos privados, apagados ou não listados não podem ser verificados. Páginas incompletas não são declaradas elegíveis.

Depois o código analisa **todos os vídeos públicos publicados dentro da janela** nos canais elegíveis, incluindo os de até 3 minutos, para medir composição por formato. Ao publicar um vídeo <=180 segundos, a API não confirma de forma confiável se ele é um Short; aparece como `ATE_3M_POSSIVEL_SHORT`. Reclassifique no arquivo `revisao_short_manual.csv` e rode novamente com `--manual-csv arquivo.csv`. Os registros manuais existentes no diretório de saída são preservados.

A pesquisa inicial usa só `medium` e `long`: canais cuja única produção é de **3 a menos de 4 minutos** podem não ser descobertos por esse caminho. O projeto é deliberadamente orientado a **long-form**, mas a opção de seed permite incluir tais canais conhecidos.

## Indicadores e arquivos gerados

Saída padrão: `resultado_radar_sem_nicho_v3/` (separada da v2).

- `auditoria_busca.csv`: país, fatia, ordenação, duração, **auditoria de ausência de `q` e de categoria**, quantidade de vídeos retornados e eventuais erros.
- `auditoria_candidatos.csv`: canal, região de descoberta, país declarado e motivo de inclusão/exclusão.
- `canais_elegiveis_analisados.csv`: proporções de publicações, proporções de views, médias, medianas, concentração dos três vídeos maiores, score e categoria do YouTube **após** a coleta.
- `videos_detalhados.csv`: todos os vídeos elegíveis, títulos, links, duração, views, views/dia e categoria pública do YouTube.
- `top50_longform_por_pais.csv`: ranking por score em cada região buscada, com até 50 canais qualificados.
- `rankings_independentes.csv`: rankings adicionais de views totais long-form, mediana por vídeo e mediana da velocidade de views/dia.
- `categorias_emergentes.csv`: categorias públicas dos vídeos longos encontrados, com views e número de canais, **não usadas para selecionar candidatos**.
- `revisao_short_manual.csv`: vídeos de até 180 segundos para confirmação manual `SHORT`/`LONG`.
- `resumo_paises.csv`: cobertura e posições não preenchidas; **não são líderes absolutos** dos países.
- `historico_snapshots.csv` e `crescimento_monitorado.csv`: histórico real dos canais rastreados e evolução calculável após 2 ou mais coletas.
- `metodologia.json`: parâmetros da execução e limitações.
- `status_coleta.json`: status `COMPLETA` ou `INTERROMPIDA_QUOTA`. Se interrompida, confira também `auditoria_busca_parcial_quota.csv`. Os rankings anteriores não são sobrescritos em falhas de cota.

**Qualificação:** por padrão, ao menos um vídeo maior que 3 minutos e 1.000 visualizações acumuladas nesses vídeos dentro da janela. A pontuação não depende de Shorts; canais mistos podem entrar. A categoria emergente é descritiva, e as médias de `<=3min` não devem ser chamadas de RPM de Shorts.

## Outras opções

```powershell
python .\radar_sem_nicho_v3.py --countries US,CA,GB,AU,DE --target 50 --days 21 --shards 4 --max-search-requests 80
python .\radar_sem_nicho_v3.py --countries US,GB --shards 8 --max-search-requests 80
python .\radar_sem_nicho_v3.py --min-long-uploads 2 --min-long-views 5000
```

`--target 50` é **meta, não garantia**. `--shards` aumenta a divisão temporal e pode consumir a cota de buscas mais rápido. `--pages-per-search` consome uma busca extra por página retornada. `--candidate-limit-per-country` limita o número de candidatos analisados por região antes da verificação; pode ocultar elegíveis.

## Cotas e custos

Segundo a documentação oficial [Quota Calculator](https://developers.google.com/youtube/data/determine_quota_cost), a cota padrão de `search.list` é **100 chamadas diárias**, em bucket separado, e há até **10.000 unidades para os demais endpoints** por dia, com alterações sujeitas à conta/projeto. O programa limita por padrão a 80 buscas e 6.000 chamadas a outros endpoints e **não evita consumo anterior no mesmo dia**. As cotas diárias reiniciam à meia-noite do Pacífico. Se você executou a v2 hoje e já gastou 80 buscas, **não rode v3 antes da renovação**. A v3.1 verifica o limite diário e **interrompe a execução sem substituir relatórios anteriores** ao receber a mensagem de cota esgotada. Erros de sobrecarga temporária continuam sujeitos a retentativas limitadas. Não há necessidade de adicionar novas bibliotecas ou pagar vidIQ.

## Leitura correta dos resultados

1. O país da busca é um **mercado explorado**, não o país de quem assiste nem o país de criação do canal.
2. A soma de views por vídeo pode não corresponder a `viewCount` acumulado informado na página do canal; **não use essa diferença como crescimento**.
3. Métricas dos vídeos são um *snapshot*, não crescimento passado. Para medir variações verdadeiras, execute em dias diferentes, sem excluir o histórico.
4. Categories do YouTube como `People & Blogs` são amplas; para encontrar subnichos reais, analise **títulos, formatos, séries e concorrência** na base detalhada.
5. Nenhuma API pública revela o RPM real de canais concorrentes; o potencial de monetização precisa ser validado por evidência comercial externa ou pelo próprio canal quando monetizado.

## Verificação rápida do código

```powershell
python -m unittest -v test_radar_sem_nicho_v3.py
```

Testes sem internet incluem validação de chamadas sem `q`, canais mistos e antigos, exclusão de vídeos públicos anteriores à janela, revisão manual de Shorts, continuidade dos snapshots, reconhecimento de 429 de limite diário e proteção contra sobrescrita de relatórios.