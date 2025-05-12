# importer/parsers/pdf_parser.py
import io
import os
import re
import logging
import tempfile
import calendar
import unicodedata # Mantém import
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple, Any
from collections import Counter

# ... (outras importações como antes) ...
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    pdfplumber = None
    logging.getLogger(__name__).critical("Biblioteca 'pdfplumber' não encontrada. Instale com 'pip install pdfplumber'.")
try:
    from dateutil.parser import parse as date_parse
except ImportError:
    date_parse = None
    logging.getLogger(__name__).warning("Biblioteca 'python-dateutil' não encontrada. Parse de datas pode ser limitado.")
from core.models import BankAccount, TransactionType
from django.conf import settings

logger = logging.getLogger(__name__)

# --- Funções Auxiliares (clean_currency, parse_reference_date - sem alterações) ---
# ... (código das funções auxiliares) ...
def clean_currency(value_str):
    if not isinstance(value_str, str) or not value_str.strip(): return Decimal('0.00')
    cleaned = re.sub(r'[.\s]', '', value_str); cleaned = re.sub(r',', '.', cleaned)
    try:
        if re.match(r'^-?\d+(\.\d+)?$', cleaned): return Decimal(cleaned)
        else: logger.warning(f"PDF Parser: Formato inesperado após limpar moeda: '{value_str}' -> '{cleaned}'"); return Decimal('0.00')
    except InvalidOperation: logger.warning(f"PDF Parser: Não converteu string moeda '{value_str}' (limpa: '{cleaned}') para Decimal."); return Decimal('0.00')
    except Exception as e: logger.error(f"PDF Parser: Erro inesperado limpando moeda '{value_str}': {e}", exc_info=True); return Decimal('0.00')

def parse_reference_date(date_str, day=21):
    if not date_str or not date_parse: return None
    cleaned_date_str = str(date_str).strip()
    if not re.match(r'^\d{1,2}/\d{4}$', cleaned_date_str): logger.warning(f"PDF Parser: Formato de data de referência inválido '{cleaned_date_str}'. Esperado MM/YYYY."); return None
    try:
        parts = cleaned_date_str.split('/'); month_int = int(parts[0]); year_int = int(parts[1])
        last_day_of_month = calendar.monthrange(year_int, month_int)[1]; actual_day = min(day, last_day_of_month)
        return date(year_int, month_int, actual_day)
    except (ValueError, IndexError) as e: logger.error(f"PDF Parser: Não parseou data '{cleaned_date_str}' ou construiu data com dia {day}. Erro: {e}"); return None
    except Exception as e_general: logger.error(f"PDF Parser: Erro inesperado parseando data '{cleaned_date_str}': {e_general}", exc_info=True); return None

# --- Normalização Helper ---
def normalize_str(text: str) -> str:
    """Normaliza string para comparação (NFKD, ASCII ignore, uppercase)."""
    if not isinstance(text, str): return ""
    try:
        # Decompõe caracteres (ex: Ê -> E + ^), converte para ASCII ignorando diacríticos, e para maiúsculas
        return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII').upper()
    except Exception:
        logger.warning(f"Falha ao normalizar texto: {text}", exc_info=True)
        return text.upper() # Retorna uppercase como fallback

# --- Parser Principal do PDF (com comparações normalizadas) ---

def parse_trt15_payslip(pdf_path: str) -> Tuple[List[Dict[str, Any]], Optional[date], Optional[str]]:
    """ Parseia holerite PDF TRT 15 usando pdfplumber. """
    if not PDFPLUMBER_AVAILABLE: return [], None, "Erro: Biblioteca pdfplumber não está instalada."
    transactions = []; reference_date = None; error_message = None; all_valid_date_strs_from_table = []; table_found = False

    try:
        logger.info(f"PDF Parser: Iniciando parse PDF com pdfplumber: {pdf_path}")
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages: return [], None, "Erro: PDF sem páginas."

            # 1. Extrair data de referência do texto
            # ... (lógica como antes) ...
            try:
                page1_text = pdf.pages[0].extract_text(x_tolerance=2, y_tolerance=2, layout=True)
                if page1_text:
                     match = re.search(r'M[ÊE]S/ANO\s+(\d{1,2}/\d{4})', page1_text, re.IGNORECASE)
                     if match:
                         ref_month_str = match.group(1); logger.info(f"PDF Parser: Data encontrada no texto da página 1: {ref_month_str}")
                         parsed_date = parse_reference_date(ref_month_str, day=21)
                         if parsed_date: reference_date = parsed_date; logger.info(f"PDF Parser: Data de referência parseada do texto: {reference_date}")
                         else: logger.warning(f"PDF Parser: Encontrou '{ref_month_str}' no texto, mas não conseguiu parsear.")
                     else: logger.warning("PDF Parser: Padrão 'MÊS/ANO MM/YYYY' não encontrado no texto da página 1.")
                else: logger.warning("PDF Parser: Não foi possível extrair texto da página 1.")
            except Exception as e_text: logger.error(f"PDF Parser: Erro ao extrair/procurar texto na página 1: {e_text}", exc_info=True)

            # 2. Extrai tabelas e processa
            # Normaliza as strings alvo UMA VEZ antes do loop
            target_rubrica = normalize_str("RUBRICA")
            target_descricao = normalize_str("DESCRIÇÃO")
            target_creditos = normalize_str("CRÉDITOS")
            target_debitos = normalize_str("DÉBITOS")
            target_mes_ref = normalize_str("MES/REF")
            required_header_parts_normalized = [target_rubrica, target_descricao, target_creditos, target_debitos]

            for i, page in enumerate(pdf.pages):
                if table_found: break
                page_num = i + 1; logger.debug(f"PDF Parser: Processando tabelas da página {page_num}")
                table_settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines", "snap_tolerance": 3}; tables = page.extract_tables(table_settings=table_settings)
                if not tables: table_settings = {"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 3, "join_tolerance": 3}; tables = page.extract_tables(table_settings=table_settings)
                if not tables: logger.debug(f"PDF Parser: Nenhuma tabela encontrada na página {page_num}."); continue

                for table_index, table in enumerate(tables):
                    if table_found: break
                    table_num = table_index + 1; logger.debug(f"PDF Parser: Analisando tabela {table_num} na página {page_num}")
                    if not table or len(table) < 2: continue

                    raw_header = table[0]
                    # Limpa header (strip, etc.) - NÃO normaliza aqui ainda
                    cleaned_header_raw = [str(cell).replace('\n', ' ').strip() if cell is not None else '' for cell in raw_header]
                    # Normaliza para verificação e mapeamento
                    cleaned_header_normalized = [normalize_str(cell) for cell in cleaned_header_raw]

                    logger.debug(f"PDF Parser: Cabeçalho extraído raw (Pg {page_num}, Tabela {table_num}): {cleaned_header_raw}")
                    logger.debug(f"PDF Parser: Cabeçalho normalizado (Pg {page_num}, Tabela {table_num}): {cleaned_header_normalized}")

                    # Verifica se o header NORMALIZADO contém as partes essenciais NORMALIZADAS
                    header_combined_normalized = " | ".join(cleaned_header_normalized)
                    is_target_table = all(part in header_combined_normalized for part in required_header_parts_normalized)

                    if is_target_table:
                        logger.info(f"PDF Parser: Tabela de rubricas ENCONTRADA (Pg {page_num}, Tabela {table_num}). Iniciando mapeamento de índices...")
                        table_found = True

                        # Mapeia índices usando o header NORMALIZADO
                        desc_idx, cred_idx, deb_idx, ref_idx = -1, -1, -1, -1
                        try:
                            for idx, header_cell_normalized in enumerate(cleaned_header_normalized):
                                # Compara com as strings alvo JÁ NORMALIZADAS
                                if target_descricao in header_cell_normalized: desc_idx = idx
                                elif target_creditos in header_cell_normalized: cred_idx = idx
                                elif target_debitos in header_cell_normalized: deb_idx = idx
                                elif target_mes_ref == header_cell_normalized: ref_idx = idx # Usa == para data ref

                            # Verifica índices essenciais de valor
                            if -1 in [desc_idx, cred_idx, deb_idx]:
                                raise ValueError(f"Não encontrou índices essenciais de valor: Desc={desc_idx}, Cred={cred_idx}, Deb={deb_idx}")
                            logger.info(f"PDF Parser: Índices mapeados FINAIS: Desc={desc_idx}, Cred={cred_idx}, Deb={deb_idx}, Ref={ref_idx}")

                        except ValueError as e_idx:
                            logger.error(f"PDF Parser: Erro ao mapear índices essenciais no cabeçalho normalizado {cleaned_header_normalized}: {e_idx}. Pulando tabela.")
                            table_found = False; continue

                        # Processa linhas de dados
                        logger.info(f"PDF Parser: Iniciando processamento das linhas da tabela encontrada...")
                        rows_processed_count = 0
                        for row_idx, row_data in enumerate(table[1:]):
                             row_num_in_table = row_idx + 1
                             try:
                                 # Limpa dados da linha (NÃO normaliza aqui)
                                 cleaned_row = [str(cell).replace('\n', ' ').strip() if cell is not None else '' for cell in row_data]
                                 if len(cleaned_row) <= max(desc_idx, cred_idx, deb_idx): continue

                                 # Pega os dados das colunas mapeadas
                                 description = cleaned_row[desc_idx]
                                 credit_str = cleaned_row[cred_idx]
                                 debit_str = cleaned_row[deb_idx]

                                 if not description and not credit_str and not debit_str: continue
                                 credit_val = clean_currency(credit_str); debit_val = clean_currency(debit_str)
                                 tx_type = None; amount = Decimal('0.00')
                                 if credit_val > 0: tx_type = 'IN'; amount = credit_val
                                 elif debit_val > 0: tx_type = 'EX'; amount = debit_val
                                 if tx_type and amount > 0:
                                     transactions.append({'description': description, 'amount': amount, 'type': tx_type})
                                     rows_processed_count += 1
                                     # Coleta data para fallback (usa índice ref_idx encontrado)
                                     if reference_date is None and ref_idx != -1 and len(cleaned_row) > ref_idx:
                                         ref_month_str_table = cleaned_row[ref_idx]
                                         if re.match(r'^\d{1,2}/\d{4}$', ref_month_str_table): all_valid_date_strs_from_table.append(ref_month_str_table)
                             except Exception as e_row: logger.exception(f"PDF Parser: Erro inesperado processando linha {row_num_in_table} da tabela.")
                        logger.info(f"PDF Parser: {rows_processed_count} linhas de dados processadas da tabela.")
                        # break # Mantém o break

            # 3. Define data de referência (fallback - como antes)
            # ... (lógica do fallback de data) ...
            if reference_date is None and all_valid_date_strs_from_table:
                 try:
                     date_counts = Counter(all_valid_date_strs_from_table); most_common_date_str = date_counts.most_common(1)[0][0]
                     logger.info(f"PDF Parser: Data de ref. não encontrada no texto. Usando mais frequente da tabela: '{most_common_date_str}'")
                     parsed_date_table = parse_reference_date(most_common_date_str, day=21)
                     if parsed_date_table: reference_date = parsed_date_table; logger.info(f"PDF Parser: Data de referência parseada da tabela (fallback): {reference_date}")
                     else: logger.error("PDF Parser: Não conseguiu parsear a data mais frequente da tabela."); error_message = error_message or "Data de referência encontrada na tabela, mas falhou ao parsear."
                 except IndexError: logger.warning("PDF Parser: Nenhuma data válida encontrada na coluna MÊS/REF da tabela para fallback.")
                 except Exception as e_fallback: logger.error(f"PDF Parser: Erro ao processar fallback de data da tabela: {e_fallback}", exc_info=True)


            # 4. Verificações finais (como antes)
            # ... (lógica das verificações finais) ...
            if not table_found: error_message = "Erro: Nenhuma tabela de rubricas compatível encontrada no PDF."; logger.error(error_message)
            elif not transactions: warning_message = "Aviso: Tabela de rubricas encontrada, mas nenhuma transação válida foi extraída."; logger.warning(warning_message); error_message = error_message or warning_message
            elif reference_date is None and not error_message and transactions: error_message = "Erro: Transações extraídas, mas data de referência (Mês/Ano) não foi encontrada."; logger.error(error_message)


    # (Blocos except e finally como antes)
    except FileNotFoundError: error_message = f"Erro: Arquivo PDF não encontrado: {pdf_path}"; logger.error(error_message)
    except ImportError: error_message = "Erro: Biblioteca pdfplumber necessária para parse PDF não está instalada."; logger.critical(error_message)
    except Exception as e: logger.exception(f"PDF Parser: Erro inesperado ao processar PDF com pdfplumber: {e}"); error_message = f"Erro inesperado ao processar o PDF: {e}"

    # Log final (como antes)
    # ... (lógica do log final) ...
    log_level = logging.ERROR if (error_message and "Aviso:" not in error_message) else logging.INFO
    summary = f"PDF Parser: Parse pdfplumber concluído: {len(transactions)} transações."
    summary += f" Data Ref: {reference_date}." if reference_date else " Data Ref: NÃO ENCONTRADA."
    if error_message: summary += f" Status Final: {error_message}"
    logger.log(log_level, summary)


    return transactions, reference_date, error_message

# --- Wrapper (chamado pela view - sem alterações) ---
# ... (código do wrapper como antes) ...
def wrapper_parse_trt15_pdf(statement_file: Any, account: BankAccount) -> Tuple[List[Dict], Optional[str]]:
    """
    Wrapper para chamar o parser PDF TRT15, gerenciando arquivo temporário
    e adaptando a saída para o formato esperado pela view (lista, erro_ou_none).
    NÃO inclui 'raw_row' para evitar problemas de serialização na sessão.
    """
    if not PDFPLUMBER_AVAILABLE: return [], "Erro: Biblioteca pdfplumber necessária para parse PDF não está instalada."
    logger.info(f"PDF Wrapper: Iniciando para conta {account.name}")
    staged_transactions = []; final_error_message = None; temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="trt15_") as temp_file:
            temp_file_path = temp_file.name;
            for chunk in statement_file.chunks(): temp_file.write(chunk)
            logger.info(f"PDF Wrapper: Arquivo PDF temporário salvo em: {temp_file_path}")
        transactions_data, reference_date, parser_error_msg = parse_trt15_payslip(temp_file_path) # Chama o parser
        if parser_error_msg and "Aviso:" not in parser_error_msg: final_error_message = parser_error_msg; logger.error(f"PDF Wrapper: Erro retornado pelo parser: {final_error_message}")
        elif not transactions_data: msg = "PDF Wrapper: Nenhuma transação encontrada no arquivo PDF."; logger.warning(msg); final_error_message = final_error_message or msg
        elif not reference_date and transactions_data: msg = "Erro: Não foi possível determinar a data de referência (Mês/Ano) do holerite."; logger.error(msg); final_error_message = msg
        elif reference_date and transactions_data: # Sucesso real
            logger.info(f"PDF Wrapper: Parser retornou {len(transactions_data)} linhas para data {reference_date}.")
            reference_date_iso = reference_date.isoformat()
            for tx_data in transactions_data:
                tx_type = None
                if tx_data.get('type') == 'IN': tx_type = TransactionType.RECEITA
                elif tx_data.get('type') == 'EX': tx_type = TransactionType.DESPESA
                if tx_type and tx_data.get('amount') is not None and tx_data['amount'] > 0:
                    # Cria o dicionário staged_tx SEM incluir 'raw_row'
                    staged_tx = {
                        'parsed_date': reference_date_iso,
                        'parsed_description': tx_data.get('description', '')[:255],
                        'parsed_amount': str(tx_data['amount']), # Já era string
                        'parsed_type': tx_type.value,
                        # 'raw_row': tx_data, # <-- REMOVIDO
                    }
                    staged_transactions.append(staged_tx)
                else: logger.warning(f"PDF Wrapper: Linha do parser PDF ignorada (tipo='{tx_data.get('type')}', valor='{tx_data.get('amount')}'). Desc: '{tx_data.get('description')}'")
            logger.info(f"PDF Wrapper: Conversão para staged_transactions concluída: {len(staged_transactions)} transações (sem raw_row).") # Log atualizado
            if not final_error_message or "Aviso:" in final_error_message: final_error_message = None
    except Exception as e: logger.exception("PDF Wrapper: Erro inesperado"); final_error_message = f"Erro interno inesperado ao processar PDF: {e}"
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try: os.remove(temp_file_path); logger.info(f"PDF Wrapper: Arquivo PDF temporário deletado: {temp_file_path}")
            except Exception as e_del: logger.error(f"PDF Wrapper: Erro ao deletar arquivo PDF temporário {temp_file_path}: {e_del}")
    if final_error_message and "Aviso:" in final_error_message: logger.warning(f"PDF Wrapper: Finalizado com aviso: {final_error_message}"); return staged_transactions, None
    elif final_error_message: logger.error(f"PDF Wrapper: Finalizado com erro: {final_error_message}"); return [], final_error_message
    else: logger.info(f"PDF Wrapper: Finalizado com sucesso ({len(staged_transactions)} transações)."); return staged_transactions, None
