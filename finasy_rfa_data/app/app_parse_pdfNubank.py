from flask import Flask, request, jsonify
import fitz # PyMuPDF
import re
from datetime import datetime
from decimal import Decimal
import sys
import os
import logging

# Tipos de transação 
class TransactionType():
    DESPESA = 'W' # Withdrawal
    RECEITA = 'D' # Deposit
    TRANSFERENCIA = 'T' # Transfer

# Configurar logging para STDOUT para que o Docker capture
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- Funções de Parsing ---

def parse_currency(value_str):
    cleaned_value = value_str.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
    is_negative = cleaned_value.startswith('-')
    if is_negative:
        cleaned_value = cleaned_value[1:]

    try:
        value = Decimal(cleaned_value)
        if is_negative:
            value = value
        return value
    except Exception as e:
        logging.error(f"Erro ao converter valor '{value_str}': {e}")
        return Decimal('0.00')

# Função para parsear a data (ex: "20 MAR" ou "28 ABR 2025")
def parse_date_with_portuguese_month(date_str):
    # Mapeamento de meses abreviados em português para números
    month_map = {
        'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAI': 5, 'JUN': 6,
        'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12
    }
    try:
        parts = date_str.strip().split(' ')
        if len(parts) == 2: # Formato "DD MMM"
            day_str, month_abbr = parts
            year = datetime.now().year # Assume ano atual se não especificado (para transações)
        elif len(parts) == 3: # Formato "DD MMM AAAA"
            day_str, month_abbr, year_str = parts
            year = int(year_str)
        else:
            logging.warning(f"Formato de data inesperado: {date_str}")
            return None

        month_num = month_map.get(month_abbr.upper()[:3]) # Garante apenas 3 letras
        if month_num:
            return datetime(year, month_num, int(day_str)).date()
    except Exception as e:
        logging.error(f"Erro ao parsear data '{date_str}': {e}")
        return None

# --- Lógica de Parsing Principal (Com Logs de Depuração) ---

def parse_pdf_content(filePath, fileName, original_email_id, email_subject):
    logging.info(f"Iniciando parsing para o arquivo: {filePath}")

    if not filePath or not os.path.exists(filePath):
        logging.error(f"Caminho do arquivo inválido ou arquivo não encontrado: {filePath}")
        return {"error": f"Arquivo não encontrado ou caminho inválido: {filePath}", "filePath": filePath}

    transactions = []
    invoice_total = None
    due_date = None
    invoice_year = None

    doc = None
    full_text = ""
    try:
        doc = fitz.open(filePath)
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            full_text += page.get_text()

        logging.info("--- Texto Completo Extraído do PDF ---")
        logging.info(full_text)
        logging.info("-------------------------------------")

        # --- Extrair Dados da Fatura (Total e Vencimento) ---
        total_match = re.search(r"Pagamento total da fatura\s*R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", full_text.replace('\n', ' '))
        if total_match:
            invoice_total_str = total_match.group(1)
            invoice_total = parse_currency(invoice_total_str)
            logging.info(f"Total da Fatura encontrado: {invoice_total}")
        else:
            logging.warning("Total da Fatura não encontrado.")


        # Corrigido: Usar a função de parse de data com meses em português
        due_date_match = re.search(r"Data de vencimento:\s*(\d{1,2}\s+\w{3}\s+\d{4})", full_text)
        if due_date_match:
            due_date_str = due_date_match.group(1)
            due_date = parse_date_with_portuguese_month(due_date_str)
            if due_date:
                invoice_year = due_date.year # Obtém o ano da fatura
                logging.info(f"Data de Vencimento encontrada: {due_date}")
            else:
                 logging.error(f"Não foi possível parsear a data de vencimento: {due_date_str}")
        else:
            logging.warning("Data de Vencimento não encontrada.")


        # --- Extrair Transações (Nova Lógica) ---
        # Regex principal para encontrar a seção de transações
        # Ajustado para ser mais flexível no início e focar no marcador de fim
        transactions_section_regex_primary = r"(TRANSAÇÕES.*?DE.*? A.*?)\n(.*?)(?:Como assegurado pela Resolução CMN|\Z)"
        transactions_section_match = re.search(transactions_section_regex_primary, full_text, re.DOTALL)

        transactions_text = ""
        if transactions_section_match:
            # Captura o grupo 2, que é o conteúdo entre o início e o fim
            transactions_text = transactions_section_match.group(2).strip()
            logging.info("Seção de transações encontrada com regex principal.")
            logging.info("--- Texto da Seção de Transações (Principal) ---")
            logging.info(transactions_text)
            logging.info("------------------------------------")
        else:
            logging.warning("Seção de transações não encontrada com regex principal. Tentando fallback...")
            # Fallback regex (mantido, pode ser útil)
            transactions_section_regex_fallback = r"TRANSAÇÕES.*?DE.*? A.*?\n(.*)"
            fallback_match = re.search(transactions_section_regex_fallback, full_text, re.DOTALL)
            if fallback_match:
                 transactions_text = fallback_match.group(1).strip()
                 logging.info("Usando fallback para seção de transações.")
                 logging.info("--- Texto da Seção de Transações (Fallback) ---")
                 logging.info(transactions_text)
                 logging.info("----------------------------------------------")
            else:
                 logging.error("Seção de transações não encontrada mesmo com fallback.")
                 pass # Nenhuma seção de transações encontrada

        # Adicionado log para ver o valor de transactions_text
        logging.info(f"transactions_text após tentativas de regex de seção: '{transactions_text}'")
        logging.info(f"Comprimento de transactions_text: {len(transactions_text)}")


        if transactions_text and invoice_year is not None:
            lines = transactions_text.split('\n')
            logging.info(f"Seção de transações dividida em {len(lines)} linhas.")

            current_transaction = {}
            # Regex para identificar linhas de data (DD MMM)
            date_line_regex = re.compile(r'^\d{1,2}\s+\w{3}$')
            # Regex para identificar linhas de valor (R$ X,XX ou -R$ X,XX)
            amount_line_regex = re.compile(r'^-?R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}$')

            cont_index = 0
            for i in range(len(lines)):
                line = lines[i].strip()
                if not line:
                    continue # Ignora linhas vazias

                # Verifica se a linha é uma data de transação
                if date_line_regex.match(line):
                    # Se já temos uma transação incompleta, algo deu errado, loga e reseta
                    if current_transaction:
                        logging.warning(f"Transação anterior incompleta. Descartando: {current_transaction}")
                    current_transaction = {'date_str': line, 'description_parts': []}
                    logging.debug(f"Encontrada linha de data: {line}")

                # Se não é uma linha de data e estamos processando uma transação
                elif current_transaction:
                    # Verifica se a linha é um valor
                    if amount_line_regex.match(line):
                        current_transaction['amount_str'] = line
                        logging.debug(f"Encontrada linha de valor: {line}")

                        # Processar a transação completa
                        date_part = current_transaction.get('date_str')
                        description_part = " ".join(current_transaction.get('description_parts', [])).strip()
                        amount_part = current_transaction.get('amount_str')

                        # Ignorar linhas que parecem ser resumos ou lixo
                        if "Saldo restante" in description_part or "Fatura anterior" in description_part or "Pagamento recebido" in description_part:
                            logging.info(f"Ignorando linha de resumo/pagamento: {description_part}")
                            current_transaction = {} # Reseta para a próxima transação
                            continue

                        transaction_date = parse_date_with_portuguese_month(date_part) # Usar a função de parse de data
                        amount = parse_currency(amount_part)
                        


                        if transaction_date and amount is not None:
                            transactions.append({
                                'date': transaction_date.isoformat(),
                                'description': description_part,
                                'amount': float(amount),
                                'type': TransactionType.DESPESA  if amount >= 0 else TransactionType.RECEITA,
                                'origin': 'cartao',
                                'file_name': fileName,
                                'item_index': cont_index
                            })
                            cont_index += 1
                            logging.debug(f"Transação parseada: {transactions[-1]}")
                        else:
                            logging.warning(f"Não foi possível parsear data ou valor para a linha: {match}")

                        current_transaction = {} # Reseta para a próxima transação

                    # Se não é linha de data nem de valor, é parte da descrição
                    else:
                        current_transaction['description_parts'].append(line)
                        logging.debug(f"Encontrada parte da descrição: {line}")

            # Verifica se há uma transação incompleta no final
            if current_transaction:
                logging.warning(f"Transação incompleta no final do arquivo. Descartando: {current_transaction}")


        else:
             logging.warning("Não há texto na seção de transações ou ano da fatura ausente para parsear transações.")


    except fitz.FileDataError as e:
        logging.error(f"Erro ao abrir ou ler o arquivo PDF (PyMuPDF): {e}")
        return {"error": f"Erro ao abrir ou ler o arquivo PDF: {e}", "filePath": filePath}
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado durante o parsing: {e}", exc_info=True) # Loga o traceback completo
        return {"error": f"Erro inesperado durante o parsing: {e}", "filePath": filePath, "details": str(e)}
    finally:
        if 'doc' in locals() and doc:
            doc.close()

    # --- Preparar Saída ---
    output_data = {
        'invoiceTotal': float(invoice_total) if invoice_total is not None else None,
        'dueDate': due_date.isoformat() if due_date else None,
        'fileName': fileName,
        'sourceFilePath': filePath,
        'transactionCount': len(transactions),
        'originalEmailId': original_email_id,
        'emailSubject': email_subject,
        'transactions': transactions
    }

    logging.info(f"Parsing concluído. Encontradas {len(transactions)} transações.")
    return output_data

# --- Endpoint HTTP ---

@app.route('/parse_pdf', methods=['POST'])
def parse_pdf_endpoint():
    try:
        data = request.get_json()
        if not data or 'filePath' not in data:
            logging.warning("Requisição inválida: 'filePath' ausente.")
            return jsonify({"error": "Requisição inválida. 'filePath' é obrigatório."}), 400

        filePath = data.get('filePath')
        fileName = data.get('fileName')
        original_email_id = data.get('originalEmailId')
        email_subject = data.get('emailSubject')

        logging.info(f"Recebida requisição para parsear arquivo: {filePath}")

        parsed_data = parse_pdf_content(filePath, fileName, original_email_id, email_subject)

        if "error" in parsed_data:
            logging.error(f"Erro no parsing do arquivo {filePath}.")
            return jsonify(parsed_data), 500
        else:
            logging.info(f"Parsing do arquivo {filePath} concluído com sucesso.")
            return jsonify(parsed_data), 200

    except Exception as e:
        logging.error(f"Erro inesperado no endpoint /parse_pdf: {e}", exc_info=True) # Loga o traceback completo
        return jsonify({"error": "Erro interno do servidor.", "details": str(e)}), 500

# --- Executar o Aplicativo Flask ---

if __name__ == '__main__':
    logging.info("Iniciando servidor Flask para parsing de PDF...")
    # Use debug=False em produção
    app.run(host='0.0.0.0', port=5000, debug=False)
