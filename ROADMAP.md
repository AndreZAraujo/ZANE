# Roadmap — YouTube Dark Channels Intelligence

**Objetivo:** descobrir canais emergentes, medir crescimento real de inscritos e visualizações, analisar oportunidades por nicho/idioma/país e apoiar decisões de criação de canais dark. O projeto usa a YouTube Data API v3, sem depender de vidIQ.

**Situação em 17/11/2026:** existe um protótipo que pesquisa vídeos recentes, coleta dados públicos e filtra canais pela primeira publicação pública conhecida. Ainda não há execução comprovada com a chave do proprietário, banco de dados histórico, testes automatizados ou relatórios recorrentes.

## Critérios de pesquisa

- **Nove mercados prioritários:** US, AU, NO, CH, CA, GB, DK, DE e NL.
- **Regra de elegibilidade:** primeiro vídeo público atualmente acessível publicado nos últimos 21 dias, **independentemente da criação da conta**. Registrar limitação para vídeos removidos/privados.
- **Rankings desejados:** 10 canais por maior crescimento de inscritos e 10 por maior crescimento de visualizações em cada país, mas **somente quando houver histórico suficiente**. Antes disso, rotular rankings de inscritos/visualizações atuais ou views dos novos uploads como **proxies**, não crescimento observado.
- **Ambiguidade geográfica:** `regionCode` da busca representa disponibilidade/mercado de pesquisa, não origem do criador nem país da audiência. País declarado pelo canal é opcional e pode divergir da audiência. Registrar o nível de evidência, e não descartar canais só por ausência de país declarado.
- **Meta de negócio:** identificar nichos cujo público potencialmente permita RPM > US$ 5. **RPM de canais terceiros não é público** e não pode ser estimado como fato comprovado.

## Fase 0 — Executar e validar o protótipo (primeiro marco)

- [ ] Configurar localmente `YOUTUBE_API_KEY` (não inserir chave, prints ou arquivos de credenciais no GitHub).
- [ ] Fazer uma consulta pequena e validar acesso/cota no Google Cloud.
- [ ] Executar coleta curta em 1 mercado e conferir 5 canais manualmente.
- [ ] Confirmar estrutura dos CSVs, tratamento de erros e consumo de quota.
- [ ] Documentar um exemplo de saída sem expor credenciais ou dados pessoais.

**Aceite:** execução real concluída, resultados revisados e custo/cota medidos.

## Fase 1 — Dados confiáveis e cobertura

- [ ] Refatorar Python em módulos: `config`, `youtube_client`, `discovery`, `validation`, `storage`, `ranking`, `reporting`.
- [ ] Tornar janela de datas dinâmica (hoje menos 21 dias), configurável por CLI.
- [ ] Implementar paginação da busca e da playlist de uploads, deduplicação por `channel_id` e `video_id`.
- [ ] Explorar vários nichos (negócios, finanças, história, ciência, software, tecnologia e curiosidades), temas por idioma e tipos de busca, sem assumir cobertura exaustiva.
- [ ] Diferenciar conta criada, primeiro **upload público conhecido**, último upload e publicações recentes.
- [ ] Separar vídeos longos, Shorts e casos indeterminados; não classificar Shorts apenas por duração.
- [ ] Guardar origem da descoberta, data/hora, mercado pesquisado, idioma e confiabilidade da localização.
- [ ] Aplicar `rate limit`, retries e contagem de quota.

**Aceite:** CSV de candidatos com status auditável, campo de primeiro upload público, URLs verificáveis e lista de motivos de exclusão.

## Fase 2 — Medir crescimento de verdade

- [ ] Adicionar armazenamento SQLite local (`channels`, `videos`, `channel_snapshots`, `video_snapshots`, `discovery_events`, `runs`).
- [ ] Salvar snapshots diários de inscritos, views totais e número de vídeos.
- [ ] Salvar snapshots dos vídeos acompanhados para calcular velocidade de views.
- [ ] Calcular `delta_inscritos_7d`, `delta_inscritos_28d`, `delta_views_7d`, `delta_views_28d` **somente quando ambas as pontas da série existirem**.
- [ ] Calcular views por vídeo, views por dia desde a publicação, crescimento relativo ao tamanho do canal e outliers.
- [ ] Exibir `sem histórico suficiente` no lugar de inventar deltas.

**Aceite:** após 7 dias de snapshots, rankings reais de 7 dias para os canais rastreados; após 28 dias, rankings reais de 28 dias.

## Fase 3 — Dashboard de oportunidades

- [ ] Interface Streamlit ou relatório Excel com filtros de país, idioma, nicho, tamanho do canal, idade editorial e formato.
- [ ] Rankings: inscritos ganhos, views ganhas, velocidade por vídeo e tração relativa à base.
- [ ] Página de cada canal: tendências, vídeos recentes, exemplos de títulos e links.
- [ ] Score de oportunidade **transparente e configurável**, baseado em crescimento, competição aparente, formato, facilidade de produção e indícios de valor comercial do nicho.
- [ ] Não representar o score como RPM observado; separar hipótese de monetização de dado confirmado.

**Aceite:** dashboard capaz de gerar uma shortlist semanal de 10–20 ideias com evidências auditáveis.

## Fase 4 — Automação e relatórios

- [ ] Configurar GitHub Actions com agendamento diário **após** teste local e cálculo de cota.
- [ ] Guardar chave apenas como GitHub Actions secret (`YOUTUBE_API_KEY`); nunca em arquivos públicos.
- [ ] Definir armazenamento persistente para snapshots (banco em host/volume persistente, serviço gerenciado ou backup versionado apropriado); filesystem efêmero do job não é banco histórico.
- [ ] Publicar CSV/XLSX e resumo de cobertura, erros e quota por execução.
- [ ] Gerar relatório semanal: 20 canais emergentes, 10 formatos promissores, riscos de replicabilidade e ideias para testar.

**Aceite:** execuções confiáveis, dados preservados entre jobs e relatório que não confunda proxies com crescimento real.

## Próxima ação concreta

1. Testar o protótipo com a chave **local** do Google Cloud, em um só país e poucos termos.
2. Enviar **apenas a saída do terminal sem a chave** e dois CSVs gerados para inspecionar problemas.
3. Refatorar para SQLite + snapshots e preparar a primeira automação.

### Regras de segurança e qualidade
- Nunca publicar API keys, dados privados, arquivos `.env` ou logs com secrets.
- Não alegar cobertura total do YouTube, país dos espectadores ou RPM real quando a API não fornece esses dados.
- Documentar hipóteses, dados faltantes e critérios de exclusão.
- Usar coleta incremental e respeitar limites do YouTube; conferir as cotas atuais em https://developers.google.com/youtube/data/determine_quota_cost.
