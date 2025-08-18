#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Processa extratos de .txt, .csv OU .pdf e exporta para XLSX com 5 colunas:
- data
- descricao
- penultimo_valor
- saldo
- linha_original

Heurísticas para PDF (para ignorar cabeçalhos/rodapés):
- Por padrão, exige data no início da linha (dd/mm/aaaa) e ao menos 2 números no padrão BR.
- Remove linhas com termos típicos de header/footer (ex.: Página, Agência, Conta, Saldo Anterior, etc.).
- Opções extras:
    --min-numbers N      : exige ao menos N números BR (padrão: 2)
    --contains "A,B,C"   : mantém apenas linhas que contenham QUALQUER destas palavras (case-insensitive)
    --no-date-filter     : não exige data no início
    --keep-all-lines     : não aplica heurísticas (modo bruto)

Dependências:
  pip install pdfplumber pandas openpyxl
"""

import re
import sys
import os
import csv
import argparse
from typing import Tuple, List
import pandas as pd

# Regex para data no início: dd/mm/aaaa
RE_DATA_INICIO = re.compile(r'^\s*(\d{2}/\d{2}/\d{4})\s+')

# Números brasileiros: aceita sinal, milhares com ponto, decimais com vírgula (e inteiros).
RE_NUM_BR = re.compile(r'(?<!\d)[+-]?\d{1,3}(?:\.\d{3})*(?:,\d+)?(?![\d,])|[+-]?\d+,\d+')
RE_NUM_BR_RUNTIME = RE_NUM_BR

STOPWORDS = [
    "PÁGINA", "PAGINA", "PÁG", "PAG", "AGÊNCIA", "AGENCIA", "CONTA", "CNPJ", "BANCO",
    "WWW", "SITE", "CENTRAL DE ATENDIMENTO", "OUVIDORIA", "ATENDIMENTO", "SAC",
    "SALDO ANTERIOR", "SALDO DO DIA", "EXTRATO", "DEMONSTRATIVO", "ENDEREÇO", "ENDERECO",
    "CPF/CNPJ", "HORÁRIO", "HORARIO"
]

def contar_numeros_br(texto: str) -> int:
    return len(RE_NUM_BR_RUNTIME.findall(texto))

def is_transaction_line(line: str, require_date: bool, min_numbers: int, contains_any: List[str]) -> bool:
    u = line.upper()
    for w in STOPWORDS:
        if w in u:
            return False
    if require_date and not RE_DATA_INICIO.match(line):
        return False
    if min_numbers > 0 and contar_numeros_br(line) < min_numbers:
        return False
    if contains_any:
        found = any(k.strip().upper() in u for k in contains_any if k.strip())
        if not found:
            return False
    return True

def extrair_campos(linha: str) -> Tuple[str, str, str, str]:
    """
    Retorna (data, descricao, penultimo_valor, saldo).
    """
    original = linha.strip()

    # Detectar data inicial
    m = RE_DATA_INICIO.match(original)
    if m:
        data = m.group(1)
        sem_data = original[m.end():]
    else:
        data = ""
        sem_data = original

    # Encontrar todos os números BR na linha sem a data
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

def process_txt(path: str) -> List[Tuple[str, str, str, str, str]]:
    rows = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            data, desc, penult, saldo = extrair_campos(line)
            rows.append((data, desc, penult, saldo, line))
    return rows

def process_csv(path: str, col: str) -> List[Tuple[str, str, str, str, str]]:
    if not col:
        raise SystemExit("--col é obrigatório para CSV.")
    rows = []
    with open(path, 'r', encoding='utf-8', errors='ignore', newline='') as fin:
        reader = csv.DictReader(fin)
        if col not in reader.fieldnames:
            raise SystemExit(f"Coluna '{col}' não encontrada. Disponíveis: {reader.fieldnames}")
        for row in reader:
            line = str(row.get(col, "") or "").strip()
            if not line:
                continue
            data, desc, penult, saldo = extrair_campos(line)
            rows.append((data, desc, penult, saldo, line))
    return rows

def process_pdf(path: str, keep_all: bool, require_date: bool, min_numbers: int, contains_any: List[str]) -> List[Tuple[str, str, str, str, str]]:
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber não instalado. Instale com: pip install pdfplumber")

    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = re.sub(r'\s+', ' ', raw.strip())
                if not line:
                    continue
                if not keep_all and not is_transaction_line(line, require_date, min_numbers, contains_any):
                    continue
                data, desc, penult, saldo = extrair_campos(line)
                rows.append((data, desc, penult, saldo, line))
    return rows

def salvar_xlsx(rows: List[Tuple[str, str, str, str, str]], out_path: str):
    df = pd.DataFrame(rows, columns=["data", "descricao", "penultimo_valor", "saldo", "linha_original"])
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="extrato")
    return out_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="Arquivo de entrada (.txt, .csv ou .pdf)")
    ap.add_argument("--col", help="Coluna com o texto (obrigatório para CSV)")
    ap.add_argument("--out", help="Caminho de saída .xlsx (opcional)")
    ap.add_argument("--keep-all-lines", action="store_true", help="No PDF, processa todas as linhas (sem heurísticas)")
    ap.add_argument("--no-date-filter", action="store_true", help="Não exige data no início da linha (PDF)")
    ap.add_argument("--min-numbers", type=int, default=2, help="Exige ao menos N números BR na linha (padrão: 2)")
    ap.add_argument("--contains", type=str, default="", help='Mantém apenas linhas que contenham QUALQUER destas palavras, separadas por vírgula. Ex.: "PIX,TARIFA,TED"')

    args = ap.parse_args()
    base, ext = os.path.splitext(args.input)
    out = args.out or (base + "_processado.xlsx")

    contains_any = [s for s in args.contains.split(",")] if args.contains else []

    ext = ext.lower()
    if ext == ".txt":
        rows = process_txt(args.input)
    elif ext == ".csv":
        rows = process_csv(args.input, args.col)
    elif ext == ".pdf":
        rows = process_pdf(
            args.input,
            keep_all=args.keep_all_lines,
            require_date=(not args.no_date_filter),
            min_numbers=args.min_numbers,
            contains_any=contains_any
        )
    else:
        raise SystemExit("Use .txt, .csv ou .pdf.")

    if not rows:
        print("Nenhuma linha processada.")
        return

    caminho = salvar_xlsx(rows, out)
    print(f"Gerado: {caminho}")

if __name__ == "__main__":
    main()
