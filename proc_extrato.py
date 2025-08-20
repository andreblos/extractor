#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Processa extratos de .txt, .csv OU .pdf e exporta para XLSX em outputs/<nome>_processado.xlsx

Colunas de saída:
- data
- descricao
- penultimo_valor  (no PDF de tabela: coluna Valor)
- saldo            (no PDF de tabela: coluna Saldo)
- linha_original

Modos PDF:
- --tables-mode        : extrai a TABELA com tolerância (recomendado p/ Sicredi)
- modo texto (padrão)  : usa heurísticas; pode combinar --no-date-filter, --min-numbers, --contains etc.

Dependências:
  pip install pandas openpyxl pdfplumber
"""

import re
import os
import csv
import argparse
from typing import Tuple, List
from pathlib import Path
import pandas as pd

# ------------------ Regex e Stopwords ------------------

# Detecta data dd/mm/aaaa no início da linha
RE_DATA_INICIO = re.compile(r'^\s*(\d{2}/\d{2}/\d{4})\s+')

# Números BR: opcional sinal, milhares com ponto e decimais com vírgula
RE_NUM_BR = re.compile(r'(?<!\d)[+-]?\d{1,3}(?:\.\d{3})*(?:,\d+)?(?![\d,])|[+-]?\d+,\d+')
RE_NUM_BR_RUNTIME = RE_NUM_BR

# Stopwords p/ limpar cabeçalho/rodapé no modo texto
STOPWORDS = [
    "PÁGINA", "PAGINA", "PÁG", "PAG", "AGÊNCIA", "AGENCIA", "CNPJ", "BANCO",
    "WWW", "SITE", "CENTRAL DE ATENDIMENTO", "OUVIDORIA", "ATENDIMENTO", "SAC",
    "SALDO DO DIA", "EXTRATO", "DEMONSTRATIVO", "ENDEREÇO", "ENDERECO",
    "CPF/CNPJ", "HORÁRIO", "HORARIO"
    # Obs: evito bloquear "CONTA" porque pode aparecer em descrição
]

# ------------------ Utilitários ------------------

def garantir_pastas():
    Path("inputs").mkdir(exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)

def limpar(s: str) -> str:
    if s is None:
        return ""
    s = re.sub(r'\s+', ' ', str(s)).strip()
    return s

def contar_numeros_br(texto: str) -> int:
    return len(RE_NUM_BR_RUNTIME.findall(texto or ""))

def is_transaction_line(line: str, require_date: bool, min_numbers: int, contains_any: List[str]) -> bool:
    u = (line or "").upper()
    for w in STOPWORDS:
        if w in u:
            return False
    if require_date and not RE_DATA_INICIO.match(line or ""):
        return False
    if min_numbers > 0 and contar_numeros_br(line) < min_numbers:
        return False
    if contains_any:
        found = any(k.strip().upper() in u for k in contains_any if k.strip())
        if not found:
            return False
    return True

# ------------ helpers p/ número BR ------------

def br_to_float(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def float_to_br(x: float) -> str:
    # formata com vírgula decimal
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# ------------------ Extração comum (TEXTO) ------------------

def extrair_campos_texto(linha: str) -> Tuple[str, str, str, str]:
    """
    Retorna (data, descricao, penultimo_valor, saldo) a partir de texto corrido.
    """
    original = (linha or "").strip()
    m = RE_DATA_INICIO.match(original)
    if m:
        data = m.group(1)
        sem_data = original[m.end():]
    else:
        data = ""
        sem_data = original

    nums = list(RE_NUM_BR_RUNTIME.finditer(sem_data))
    if len(nums) >= 2:
        penult_match = nums[-2]
        penultimo_valor = penult_match.group(0)
        saldo = nums[-1].group(0)
        descricao = sem_data[:penult_match.start()].rstrip()
        descricao = re.sub(r'\s+', ' ', descricao).strip()
    elif len(nums) == 1:
        penultimo_valor = ""
        saldo = nums[-1].group(0)
        descricao = re.sub(r'\s+', ' ', sem_data).strip()
    else:
        penultimo_valor = ""
        saldo = ""
        descricao = re.sub(r'\s+', ' ', sem_data).strip()
    return data, descricao, penultimo_valor, saldo

def process_txt(path: Path) -> List[Tuple[str, str, str, str, str]]:
    rows = []
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            data, desc, penult, saldo = extrair_campos_texto(line)
            rows.append((data, desc, penult, saldo, line))
    return rows

def process_csv(path: Path, col: str) -> List[Tuple[str, str, str, str, str]]:
    if not col:
        raise SystemExit("--col é obrigatório para CSV.")
    rows = []
    with path.open('r', encoding='utf-8', errors='ignore', newline='') as fin:
        reader = csv.DictReader(fin)
        if col not in reader.fieldnames:
            raise SystemExit(f"Coluna '{col}' não encontrada. Disponíveis: {reader.fieldnames}")
        for row in reader:
            line = str(row.get(col, "") or "").strip()
            if not line:
                continue
            data, desc, penult, saldo = extrair_campos_texto(line)
            rows.append((data, desc, penult, saldo, line))
    return rows

# ------------------ Extração PDF (TABELA TOLERANTE) ------------------

def process_pdf_tables(path: Path) -> List[Tuple[str, str, str, str, str]]:
    """
    Extrai a TABELA do PDF (ex.: Sicredi) de forma tolerante:
    - Junta as células por linha
    - Toma os DOIS últimos números BR como (valor, saldo)
    - Descrição = texto entre a data e o penúltimo número
    - Detecta 'SALDO ANTERIOR' para iniciar saldo corrente (fallback)
    """
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber não instalado. Instale com: pip install pdfplumber")

    rows = []
    saldo_corrente = None  # float
    settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 5,
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "text_x_tolerance": 2,
        "text_y_tolerance": 2,
        "min_words_vertical": 1,
        "min_words_horizontal": 1,
    }

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            try:
                tables = page.extract_tables(settings)
            except Exception:
                tables = page.extract_tables()

            for tb in tables or []:
                for r in tb or []:
                    cells = [limpar(c) for c in r if c is not None]
                    if not any(cells):
                        continue

                    joined_upper = " ".join(cells).upper()
                    # Remove títulos/cabeçalhos
                    if joined_upper.startswith("EXTRATO ") or "PERÍODO DE" in joined_upper or "PERIODO DE" in joined_upper:
                        continue
                    if "DATA" in joined_upper and "DESCRI" in joined_upper and "VALOR" in joined_upper:
                        continue

                    joined = " | ".join(cells)           # para linha_original
                    flat = " ".join(cells)               # para parsing
                    if not flat:
                        continue

                    # Detecta SALDO ANTERIOR
                    if "SALDO ANTERIOR" in joined_upper:
                        nums = RE_NUM_BR.findall(flat)
                        if nums:
                            saldo_corrente = br_to_float(nums[-1])
                            rows.append(("", "SALDO ANTERIOR", "", nums[-1], joined))
                        continue

                    # Extrai data (se houver)
                    mdata = RE_DATA_INICIO.match(flat)
                    data = mdata.group(1) if mdata else ""
                    resto = flat[mdata.end():].strip() if mdata else flat

                    # Dois últimos números = (valor, saldo)
                    nums = RE_NUM_BR.findall(resto)
                    penultimo_valor = ""
                    saldo_str = ""
                    descricao = ""

                    if len(nums) >= 2:
                        penultimo_valor = nums[-2]
                        saldo_str = nums[-1]
                        # descrição até o início do penúltimo número
                        idx_penult = resto.rfind(penultimo_valor)
                        descricao = resto[:idx_penult].strip() if idx_penult != -1 else resto
                    elif len(nums) == 1:
                        # Só veio o valor; saldo via saldo_corrente (se existir)
                        penultimo_valor = nums[0]
                        if saldo_corrente is not None:
                            saldo_corrente = saldo_corrente + br_to_float(penultimo_valor)
                            saldo_str = float_to_br(saldo_corrente)
                        idx = resto.rfind(penultimo_valor)
                        descricao = resto[:idx].strip() if idx != -1 else resto
                    else:
                        # Sem números, provavelmente ruído
                        continue

                    # Atualiza saldo corrente se temos saldo_str
                    if saldo_str:
                        saldo_corrente = br_to_float(saldo_str)

                    descricao = re.sub(r'\s+', ' ', descricao).strip()
                    linha_original = joined.strip(" |")
                    rows.append((data, descricao, penultimo_valor, saldo_str, linha_original))

    return rows

# ------------------ Extração PDF (TEXTO – fallback genérico) ------------------

def process_pdf_text(path: Path, keep_all: bool, require_date: bool, min_numbers: int, contains_any: List[str]) -> List[Tuple[str, str, str, str, str]]:
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber não instalado. Instale com: pip install pdfplumber")

    rows = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = limpar(raw)
                if not line:
                    continue
                if not keep_all and not is_transaction_line(
                    line,
                    require_date=require_date,
                    min_numbers=min_numbers,
                    contains_any=contains_any
                ):
                    continue
                data, desc, penult, saldo = extrair_campos_texto(line)
                rows.append((data, desc, penult, saldo, line))
    return rows

# ------------------ Gravação ------------------

def salvar_xlsx(rows: List[Tuple[str, str, str, str, str]], out_path: Path):
    df = pd.DataFrame(rows, columns=["data", "descricao", "penultimo_valor", "saldo", "linha_original"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(str(out_path), engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="extrato")
    return out_path

# ------------------ Main ------------------

def main():
    garantir_pastas()

    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="Arquivo (.txt, .csv ou .pdf) dentro de inputs/")
    ap.add_argument("--col", help="(CSV) Nome da coluna com o texto")
    ap.add_argument("--out", help="Saída .xlsx (padrão: outputs/<base>_processado.xlsx)")

    # Opções para PDF em modo texto
    ap.add_argument("--keep-all-lines", action="store_true", help="(PDF texto) Processa todas as linhas (sem heurísticas)")
    ap.add_argument("--no-date-filter", action="store_true", help="(PDF texto) Não exige data no início da linha")
    ap.add_argument("--min-numbers", type=int, default=2, help="(PDF texto) Exige ao menos N números BR por linha (padrão: 2)")
    ap.add_argument("--contains", type=str, default="", help='(PDF texto) Mantém linhas que contenham QUALQUER destas palavras (separadas por vírgula)')

    # Modo tabela tolerante
    ap.add_argument("--tables-mode", action="store_true", help="(PDF) Extrai como TABELA tolerante (recomendado p/ Sicredi)")

    args = ap.parse_args()

    base_name = Path(args.input).name
    input_path = Path("inputs") / base_name
    if not input_path.exists():
        raise SystemExit(f"Arquivo {input_path} não encontrado. Coloque-o em inputs/")

    base = input_path.stem
    out_path = Path(args.out) if args.out else Path("outputs") / f"{base}_processado.xlsx"

    ext = input_path.suffix.lower()
    if ext == ".txt":
        rows = process_txt(input_path)
    elif ext == ".csv":
        rows = process_csv(input_path, args.col)
    elif ext == ".pdf":
        if args.tables_mode:
            rows = process_pdf_tables(input_path)
            # fallback caso a tabela não seja detectada
            if not rows:
                rows = process_pdf_text(
                    input_path,
                    keep_all=args.keep_all_lines,
                    require_date=(not args.no_date_filter),
                    min_numbers=args.min_numbers,
                    contains_any=[s for s in args.contains.split(",")] if args.contains else []
                )
        else:
            rows = process_pdf_text(
                input_path,
                keep_all=args.keep_all_lines,
                require_date=(not args.no_date_filter),
                min_numbers=args.min_numbers,
                contains_any=[s for s in args.contains.split(",")] if args.contains else []
            )
    else:
        raise SystemExit("Use .txt, .csv ou .pdf.")

    if not rows:
        print("Nenhuma linha processada.")
        return

    caminho = salvar_xlsx(rows, out_path)
    print(f"Gerado: {caminho}")

if __name__ == "__main__":
    main()
