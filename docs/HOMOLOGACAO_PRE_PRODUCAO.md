# Homologação pré-produção — Imob ERP

Este roteiro separa o que pode ser validado automaticamente do que exige uma pessoa responsável pela operação da imobiliária. Nenhuma etapa autoriza uso de credenciais de produção em testes destrutivos.

## 1. Gate técnico automático

Antes de iniciar a homologação humana, o commit candidato deve concluir no GitHub Actions:

- segurança do histórico Git;
- typecheck e build do frontend;
- compilação e testes do backend em PostgreSQL descartável;
- migrations Alembic;
- jornadas críticas automatizadas;
- build do container;
- deploy do SHA exato no Cloud Run;
- health, readiness, banco e autenticação após o deploy.

Se o job `deploy` aparecer como `skipped`, confirmar a variável `GCP_WIF_READY=true` e as variáveis WIF do repositório antes de considerar a versão publicada.

## 2. Jornada operacional com dados fictícios

Executar nesta ordem e registrar evidência do resultado:

1. cadastrar proprietário, locatário e corretor fictícios;
2. cadastrar e publicar um imóvel de teste;
3. criar lead, visita, proposta e converter a proposta aceita;
4. gerar contrato de administração e contrato de locação;
5. gerar documentos e validar os hashes;
6. simular assinatura com provider de teste;
7. gerar cobrança, registrar recebimento e conciliar o extrato;
8. gerar comissão e repasse ao proprietário;
9. preparar, aprovar e executar lote com três usuários distintos;
10. confirmar que o preparador não aprova o próprio lote;
11. fechar a competência e confirmar o bloqueio retroativo;
12. reabrir com usuário autorizado e justificativa;
13. conferir DRE, extrato do proprietário e trilha de auditoria.

Resultado esperado: nenhum saldo duplicado, nenhuma mistura entre recursos próprios e de terceiros e todos os atores identificados.

## 3. Homologação Banco Inter

Começar no sandbox. A pessoa responsável deve confirmar:

- conta, agência e ambiente corretos;
- teste de conexão aprovado em Configurações → Integrações;
- saldo compatível com o ambiente bancário;
- cobrança de valor simbólico criada uma única vez;
- webhook recebido sem duplicidade;
- baixa e conciliação com valor e data corretos;
- Pix de teste submetido uma única vez e acompanhado até o estado final.

Nunca homologar pagamentos na conta de produção sem autorização expressa e conferência do favorecido.

## 4. Homologação Clicksign

Começar no sandbox e confirmar:

- signatários, documentos e ordem de assinatura;
- recebimento das notificações;
- recusa e cancelamento quando aplicáveis;
- webhook HMAC aceito e evento duplicado tratado de forma idempotente;
- PDF final válido, arquivado no storage próprio e com SHA-256 registrado;
- contrato marcado como assinado somente após o arquivamento final.

## 5. Aceite empresarial

A direção da imobiliária deve aprovar por escrito:

- matriz de usuários e permissões;
- alçadas e exceções de segregação;
- regras de multa, juros, comissão e repasse;
- calendário de fechamento e responsáveis pela reabertura;
- modelos contratuais e comunicações;
- plano de contas e classificações financeiras;
- política de contingência quando banco ou assinatura estiverem indisponíveis.

## 6. Critério de liberação

A versão só deve ser promovida para operação definitiva quando:

- todos os gates técnicos estiverem verdes;
- o SHA publicado for o mesmo SHA aprovado;
- Banco Inter e Clicksign estiverem homologados ou formalmente desativados;
- a jornada operacional estiver concluída sem divergência financeira;
- os responsáveis aceitarem as regras e os documentos gerados.
