# Extractor

Um projeto simples para **extração e organização de dados** a partir de arquivos da empresa (como planilhas e extratos), com salvamento automático dos resultados na pasta `outputs/`.

## 🚀 Funcionalidades
- Lê arquivos de entrada (planilhas, extratos, PDFs etc.)
- Processa e organiza os dados
- Gera relatórios/resultados em formato Excel ou PDF
- Salva tudo na pasta `outputs/` (que não é versionada no Git)

## 📂 Estrutura do Projeto
extractor/
│-- src/ # Código-fonte do projeto
│-- outputs/ # Resultados gerados (ignorado pelo Git)
│-- .gitignore # Arquivos/pastas ignorados no versionamento
│-- README.md # Documentação do projeto


## ⚙️ Pré-requisitos
- [Git](https://git-scm.com/)  
- [Java](https://www.oracle.com/java/) ou [Python](https://www.python.org/) *(dependendo da linguagem do projeto)*  
- Dependências listadas no arquivo de configuração (`pom.xml`, `requirements.txt`, etc.)

## 💻 Como usar
1. Clone o repositório:
   ```bash
   git clone git@github.com:andreblos/extractor.git
   cd extractor

2. Execute o projeto:

python main.py

3. Coloque seus arquivos de entrada na pasta definida pelo sistema.

4. Verifique os resultados na pasta:

outputs/

🛡️ Observações

Arquivos sensíveis (como planilhas de extratos e PDFs) não são versionados.

Apenas o código-fonte e a estrutura do projeto são mantidos no repositório.

📄 Licença

Este projeto é de uso privado da empresa e não deve ser utilizado para fins comerciais sem autorização.