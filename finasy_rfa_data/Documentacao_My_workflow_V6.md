# My workflow

## Visão Geral

Este documento descreve a configuração e o fluxo de um workflow automatizado.

## Nós (Nodes)

O workflow é composto pelos seguintes nós:

### 1. Gmail Trigger
* **ID:** `777d216f-10ce-4b79-b9d2-fe7c1aeb0dcd`
* **Tipo:** `n8n-nodes-base.gmailTrigger` (Versão 1.2)
* **Posição:** [-1620, -520]
* **Parâmetros:**
    * Verifica e-mails a cada hora (`pollTimes`: `everyHour`).
    * Não é uma configuração simples (`simple`: false).
    * **Filtros:**
        * Busca por e-mails não lidos (`readStatus`: "unread").
        * Remetente: `todomundo@nubank.com.br` (`sender`).
    * **Opções:**
        * Baixar anexos (`downloadAttachments`: true).
* **Credenciais:**
    * `gmailOAuth2`:
        * ID: `w2qVtx1MJd1BSwkp`
        * Nome: `Gmail account`

### 2. Code (Extract Attachments)
* **ID:** `b3b09ba2-91f8-45cd-8a53-320fcd2ac989`
* **Nome:** Code (Extract Attachments)
* **Tipo:** `n8n-nodes-base.code` (Versão 2)
* **Posição:** [-1300, -520]
* **Parâmetros:**
    * **Linguagem:** python
    * **Código Python:**
        ```python
        # Lista que armazenará os itens processados (cada anexo será um item independente)
        results = []

        # Itera sobre cada e-mail capturado pelo Gmail Trigger
        for email in items:
            # Acessa os dados binários (anexos) do e-mail
            binary_data = email['binary']
            # Obtém o ID do e-mail original a partir da saída do trigger
            original_email_id = email['json']['id']

            # Itera sobre cada chave (nome do arquivo) nos anexos
            for file_key in binary_data:
                # Cria um NOVO ITEM para cada anexo
                new_item = {
                    'json': {
                        'originalEmailId': original_email_id,
                        'fileName': binary_data[file_key]['fileName'],
                        'mimeType': binary_data[file_key]['mimeType'],
                        'emailSubject': email['json']['subject']
                    },
                    'binary': {
                        'data': {
                            'data': binary_data[file_key]['data'],
                            'mimeType': binary_data[file_key]['mimeType'],
                            'fileName': binary_data[file_key]['fileName']
                        }
                    }
                }
                results.append(new_item)

        return results
        ```

### 3. Save Attachment to Staging
* **ID:** `f70998b1-d052-47af-9844-f16afcb18fcf`
* **Nome:** Save Attachment to Staging
* **Tipo:** `n8n-nodes-base.readWriteFile` (Versão 1)
* **Posição:** [-1060, -520]
* **Parâmetros:**
    * **Operação:** `write`
    * **Nome do Arquivo:** `=/shared_staging/{{ $json.fileName }}`
    * **Opções:**
        * `append`: false (sobrescreve o arquivo se existir)

### 4. HTTP Request (Call Parser Service)
* **ID:** `c8d6c566-7e4a-4205-b089-8ea9cad14ba6`
* **Nome:** HTTP Request (Call Parser Service)
* **Tipo:** `n8n-nodes-base.httpRequest` (Versão 3)
* **Posição:** [-780, -520]
* **Parâmetros:**
    * **Método:** `POST`
    * **URL:** `http://parser_service_rfa:5000/parse_pdf`
    * **Enviar Corpo:** true (`sendBody`)
    * **Parâmetros do Corpo:**
        * `filePath`: `={{ $json.fileName }}`
        * `fileName`: `={{ $('Code (Extract Attachments)').item.json.fileName }}`
        * `originalEmailId`: `={{ $('Code (Extract Attachments)').item.json.originalEmailId }}`
        * `emailSubject`: `={{ $json.emailSubject }}`
    * **Opções:** {}

### 5. Telegram Notification
* **ID:** `1f22d60e-35db-4206-ad12-f4dc580865d6`
* **Nome:** Telegram Notification
* **Tipo:** `n8n-nodes-base.telegram` (Versão 1)
* **Posição:** [-440, -580]
* **Parâmetros:**
    * **Chat ID:** `5302038938`
    * **Texto:** `={{ $json.transactionCount }} transações encontradas na fatura Total: R$ {{ $json.invoiceTotal }}. Vencimento: {{ $json.dueDate }}`
    * **Campos Adicionais:** {}
* **Webhook ID:** `e5211e39-f61b-4bc6-98fd-7d49fa8babb5`
* **Sempre Gerar Saída:** true (`alwaysOutputData`)
* **Credenciais:**
    * `telegramApi`:
        * ID: `I5WFjV3S0k3LRxRU`
        * Nome: `Telegram account`

### 6. Gmail
* **ID:** `51bcf2d8-6423-43fc-8585-fe45f38a0f2a`
* **Nome:** Gmail
* **Tipo:** `n8n-nodes-base.gmail` (Versão 2.1)
* **Posição:** [-440, -420]
* **Parâmetros:**
    * **Operação:** `markAsRead` (marcar como lido)
    * **ID da Mensagem:** `={{ $json.originalEmailId }}`
* **Webhook ID:** `e0c91aeb-7913-4994-ae8e-06ad9947f4e6`
* **Credenciais:**
    * `gmailOAuth2`:
        * ID: `w2qVtx1MJd1BSwkp`
        * Nome: `Gmail account`

### 7. Split Out Transactions
* **ID:** `60358156-6fa3-4762-a6f5-3f223cfa3ad9`
* **Nome:** Split Out Transactions
* **Tipo:** `n8n-nodes-base.splitOut` (Versão 1)
* **Posição:** [-1620, -260]
* **Parâmetros:**
    * **Campo para Dividir:** `=transactions`
    * **Opções:**
        * `destinationFieldName`: "" (nome do campo de destino vazio)
* **Sempre Gerar Saída:** false (`alwaysOutputData`)

### 8. Postgres (Search Payee)
* **ID:** `f9281298-ee48-48bb-bf7d-3b0f9bbbd338`
* **Nome:** Postgres (Search Payee)
* **Tipo:** `n8n-nodes-base.postgres` (Versão 2.6)
* **Posição:** [-1140, -80]
* **Parâmetros:**
    * **Operação:** `executeQuery`
    * **Query:**
        ```sql
        SELECT
            p.id,
            p.name,
            COUNT(p.id) AS nr_trans,
            {{ $json.amount }},
            {{ $json.item_index }} as item_index
        FROM public.core_payeepayer p
        INNER JOIN public.core_transaction t ON p.id = t.payee_payer_id
        WHERE p.name LIKE '%{{ $json.description }}%'
        GROUP BY p.id
        ORDER BY nr_trans DESC, p.name ASC
        LIMIT 1
        ```
    * **Opções:**
        * `queryReplacement`: `={{ $json.description }}`
* **Sempre Gerar Saída:** true (`alwaysOutputData`)
* **Credenciais:**
    * `postgres`:
        * ID: `JBCN6txcbThrVjxj`
        * Nome: `Postgres account`

### 9. Code (Add item\_index to Payee Results)
* **ID:** `df0f9747-c477-4037-95fc-673c95004405`
* **Nome:** Code (Add item\_index to Payee Results)
* **Tipo:** `n8n-nodes-base.code` (Versão 2)
* **Posição:** [-920, -80]
* **Parâmetros:**
    * **Linguagem:** python
    * **Código Python:**
        ```python
        # Este script recebe a lista de dicionários retornada pelo nó Postgres (Search Payee)
        # items contém a lista de dicionários

        output_items = []

        # Itera sobre os dicionários retornados pelo Postgres
        for i, result_dict in enumerate(items):
            # Acessa o item_index original do item de entrada para este nó Code
            # O item de entrada para este nó Code é o resultado da busca no Postgres.
            # O item_index original está no contexto do item de entrada.
            original_item_index = None
            # Acessa o item de entrada do n8n para este item de resultado
            # No nó Code, o item de entrada correspondente ao item de saída atual é item.context.item
            # No contexto, o item_index original é geralmente acessível via item.context.item.json.item_index
            # ou item.context.itemIndex

            # Tentativa 1: Acessar do contexto do item de entrada (formato item.context.item.json.item_index)
            # Verifica se o item de entrada existe no contexto e tem a estrutura esperada
            if hasattr(result_dict, 'context') and result_dict.context and 'item' in result_dict.context and \
               hasattr(result_dict.context['item'], 'json') and result_dict.context['item'].json and \
               'item_index' in result_dict.context['item'].json:
                 original_item_index = result_dict.context['item'].json['item_index']
            # Tentativa 2: Acessar do contexto do item de entrada (formato item.context.itemIndex)
            elif hasattr(result_dict, 'context') and result_dict.context and 'itemIndex' in result_dict.context:
                 original_item_index = result_dict.context['itemIndex']
            # Tentativa 3: Acessar diretamente do item (menos provável para resultados de DB)
            # Esta tentativa é menos relevante agora que sabemos que a entrada são dicionários crus
            # elif hasattr(result_dict, 'json') and result_dict.json and 'item_index' in result_dict.json:
            #      original_item_index = result_dict.json['item_index']


            # Adiciona o item_index original ao dicionário de saída
            # Modifica o dicionário diretamente
            result_dict['original_item_index'] = original_item_index

            # Adiciona o dicionário modificado à lista de saída
            # O nó Code retorna dicionários como itens com .json
            output_items.append({'json': result_dict})

        # Retorna a lista de itens (com .json) contendo os dicionários do Postgres + original_item_index
        return output_items
        ```
* **Sempre Gerar Saída:** true (`alwaysOutputData`)

### 10. Set Transaction Fields
* **ID:** `658c1463-8807-48ac-a0a6-4fee429e7f12`
* **Nome:** Set Transaction Fields
* **Tipo:** `n8n-nodes-base.set` (Versão 3.4)
* **Posição:** [-1460, -80]
* **Parâmetros:**
    * **Atribuições (`assignments`):**
        * `reference_month`: `={{ $('HTTP Request (Call Parser Service)').item.json.dueDate.split('-')[1] }} ` (string)
        * `reference_year`: `={{ $('HTTP Request (Call Parser Service)').item.json.dueDate.split('-')[0] }}` (string)
        * `notes`: `={{ $json.description.includes('Parcela') ? $json.description.split(' - ')[1] : null }} ` (string)
        * `created_at`: `={{ $now }} ` (string)
        * `updated_at`: `={{ $now }} ` (string)
        * `status`: `=N` (string)
        * `origin`: `=cartao` (string)
        * `account_id`: `38` (string)
        * `user_id`: `2` (string)
        * (campo vazio): "" (string)
        * `item_index`: `={{ $json.item_index }}` (number)
    * **Opções:** {}
* **Sempre Gerar Saída:** false (`alwaysOutputData`)

### 11. Set (Assign Payee ID)
* **ID:** `74fade27-6015-48c2-b714-4cbc1552e13b`
* **Nome:** Set (Assign Payee ID)
* **Tipo:** `n8n-nodes-base.set` (Versão 3.4)
* **Posição:** [-520, -220]
* **Parâmetros:**
    * **Atribuições (`assignments`):**
        * `payee_payer_id`: `={{ $json.json.id }}` (string)
    * **Incluir Outros Campos:** true (`includeOtherFields`)
    * **Opções:** {}

### 12. Merge (Payee Results)
* **ID:** `25746dca-5a3b-4bee-8db6-b5ae880c2170`
* **Nome:** Merge (Payee Results)
* **Tipo:** `n8n-nodes-base.merge` (Versão 3.1)
* **Posição:** [-760, -220]
* **Parâmetros:**
    * **Modo:** `combine`
    * **Avançado:** true
    * **Mesclar por Campos (`mergeByFields`):**
        * `field1`: `item_index`
        * `field2`: `json.item_index`
    * **Modo de Junção (`joinMode`):** `keepEverything` (manter tudo)
    * **Opções:** {}
* **Sempre Gerar Saída:** true (`alwaysOutputData`)

### 13. Merge (Transactions and Fields)
* **ID:** `07b72dd1-5a0a-4dd2-9825-85314ae918f8`
* **Nome:** Merge (Transactions and Fields)
* **Tipo:** `n8n-nodes-base.merge` (Versão 3.1)
* **Posição:** [-1300, -240]
* **Parâmetros:**
    * **Modo:** `combine`
    * **Avançado:** true
    * **Mesclar por Campos (`mergeByFields`):**
        * `field1`: `item_index`
        * `field2`: `item_index`
    * **Opções:** {}

### 14. Code (Clear Transaction)
* **ID:** `ec51472f-67ab-4799-a908-5a86f8b04c82`
* **Nome:** Code (Clear Transaction)
* **Tipo:** `n8n-nodes-base.code` (Versão 2)
* **Posição:** [-220, -220]
* **Parâmetros:**
    * **Código JS:**
        ```javascript
        return items.map(item => {
            // Remover o campo 'json'
            delete item.json.json;
            delete item.binary;
            delete item.pairedItem;
            delete item.json.pairedItem;

          // Se 'payee_pay_id' for null, definir um valor fixo
            if (item.json.payee_payer_id === null) {
                item.json.payee_payer_id = 1975; // Defina o valor fixo desejado
            }

            return { json: item };
        });
        ```

### 15. Merge (Category Results)
* **ID:** `056877fb-1ee7-4be8-a494-bf44295162db`
* **Nome:** Merge (Category Results)
* **Tipo:** `n8n-nodes-base.merge` (Versão 3.1)
* **Posição:** [500, -240]
* **Parâmetros:**
    * **Modo:** `combine`
    * **Avançado:** true
    * **Mesclar por Campos (`mergeByFields`):**
        * `field1`: `item_index`
        * `field2`: `json.item_index`
    * **Modo de Junção (`joinMode`):** `keepEverything` (manter tudo)
    * **Opções:** {}

### 16. Set (Assign Category ID)
* **ID:** `027a819c-6bcb-4dc4-9fc4-15a3f361fecd`
* **Nome:** Set (Assign Category ID)
* **Tipo:** `n8n-nodes-base.set` (Versão 3.4)
* **Posição:** [300, -460]
* **Parâmetros:**
    * **Modo:** `raw`
    * **Saída JSON:**
        ```json
        {
          "item_index": {{ $('Code (Clear Transaction)').item.json.json.item_index }}
        }
        ```
    * **Incluir Outros Campos:** true (`includeOtherFields`)
    * **Opções:** {}
* **Sempre Gerar Saída:** false (`alwaysOutputData`)
* **Executar Uma Vez:** false (`executeOnce`)

### 17. Postgres (Insert Transaction)
* **ID:** `6c9321a5-b901-4605-9556-424a6b84c9cc`
* **Nome:** Postgres (Insert Transaction)
* **Tipo:** `n8n-nodes-base.postgres` (Versão 2.6)
* **Posição:** [740, -240]
* **Parâmetros:**
    * **Schema:** `public`
    * **Tabela:** `core_transaction`
    * **Colunas (Mapeamento):**
        * `is_recurring_payment`: false
        * `amount`: `={{ $json.json.amount }}`
        * `reference_month`: `={{ $json.json.reference_month }}`
        * `reference_year`: `={{ $json.json.reference_year }}`
        * `account_id`: `={{ $json.json.account_id }}`
        * `category_id`: `={{ $json.category_id }}`
        * `payee_payer_id`: `={{ $json.json.payee_payer_id }}`
        * `user_id`: `={{ $json.json.user_id }}`
        * `description`: `={{ $json.json.description }}`
        * `date`: `={{ $json.json.date }}`
        * `notes`: `={{ $json.json.notes }}`
        * `created_at`: `={{ $now }}`
        * `updated_at`: `={{ $now }}`
        * `status`: `={{ $json.json.status }}`
        * `type`: `={{ $json.json.type }}`
    * **Opções:** {}
* **Sempre Gerar Saída:** true (`alwaysOutputData`)
* **Notas no Fluxo:** false (`notesInFlow`)
* **Credenciais:**
    * `postgres`:
        * ID: `JBCN6txcbThrVjxj`
        * Nome: `Postgres account`

### 18. Postgres (Search Last Category by Payee)
* **ID:** `568d259e-98b2-405e-8b74-ce632fc2c93e`
* **Nome:** Postgres (Search Last Category by Payee)
* **Tipo:** `n8n-nodes-base.postgres` (Versão 2.6)
* **Posição:** [40, -460]
* **Parâmetros:**
    * **Operação:** `select`
    * **Schema:** `public`
    * **Tabela:** `core_transaction`
    * **Limite:** 1
    * **Condição `WHERE`:**
        * `payee_payer_id`: `={{ $json.json.payee_payer_id }}`
        * `category_id`: `IS NOT NULL`
    * **Ordenação `SORT`:**
        * `date`: `DESC`
        * `created_at`: `DESC`
    * **Opções:**
        * `outputColumns`: `={{ ["category_id"] }}`
* **Sempre Gerar Saída:** true (`alwaysOutputData`)
* **Executar Uma Vez:** false (`executeOnce`)
* **Notas no Fluxo:** false (`notesInFlow`)
* **Credenciais:**
    * `postgres`:
        * ID: `JBCN6txcbThrVjxj`
        * Nome: `Postgres account`

## Conexões

As conexões definem o fluxo de dados entre os nós:

* **Gmail Trigger** -> `Code (Extract Attachments)`
* **Code (Extract Attachments)** -> `Save Attachment to Staging`
* **Save Attachment to Staging** -> `HTTP Request (Call Parser Service)`
* **HTTP Request (Call Parser Service)** ->
    * `Telegram Notification`
    * `Gmail`
    * `Split Out Transactions`
* **Split Out Transactions** ->
    * `Set Transaction Fields`
    * `Merge (Transactions and Fields)`
* **Postgres (Search Payee)** -> `Code (Add item_index to Payee Results)`
* **Code (Add item_index to Payee Results)** -> `Merge (Payee Results)` (entrada 1)
* **Set Transaction Fields** -> `Merge (Transactions and Fields)` (entrada 1)
* **Set (Assign Payee ID)** -> `Code (Clear Transaction)`
* **Merge (Payee Results)** -> `Set (Assign Payee ID)`
* **Merge (Transactions and Fields)** ->
    * `Postgres (Search Payee)`
    * `Merge (Payee Results)` (entrada 0)
* **Code (Clear Transaction)** ->
    * `Postgres (Search Last Category by Payee)`
    * `Merge (Category Results)` (entrada 1)
* **Merge (Category Results)** -> `Postgres (Insert Transaction)`
* **Set (Assign Category ID)** -> `Merge (Category Results)` (entrada 0)
* **Postgres (Search Last Category by Payee)** -> `Set (Assign Category ID)`

## Configurações (Settings)

* **Ordem de Execução:** `v1`
* **Fuso Horário:** `America/Sao_Paulo`
* **Política de Chamada (Caller Policy):** `workflowsFromSameOwner` (workflows do mesmo proprietário)

## Status

* **Ativo:** `false`

## ID da Versão

* `c6b59fbb-3b18-49f4-abb5-8d7f03f67a10`

## Meta Informações

* `templateCredsSetupCompleted`: true
* `instanceId`: `3dc0039cd964bb558e3cf6baca2759a85b34bc70753f389defcfd1d21f5543c5`

## ID

* `NuiWafwmHxhzkqwa`

## Tags

* (Nenhuma tag definida)