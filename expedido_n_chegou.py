import pandas as pd
import os
import glob
import math
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import numpy as np
import shutil
import questionary 

# --- DICIONÁRIO DE TRADUÇÃO DE ESTADOS (PARA O MAPA NO LOOKER) ---
mapa_estados = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas', 'BA': 'Bahia',
    'CE': 'Ceará', 'DF': 'Distrito Federal', 'ES': 'Espírito Santo', 'GO': 'Goiás',
    'MA': 'Maranhão', 'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais',
    'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco', 'PI': 'Piauí',
    'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte', 'RS': 'Rio Grande do Sul',
    'RO': 'Rondônia', 'RR': 'Roraima', 'SC': 'Santa Catarina', 'SP': 'São Paulo',
    'SE': 'Sergipe', 'TO': 'Tocantins'
}


# --- COLETA DE INFORMAÇÕES DO USUÁRIO (COM MENU INTERATIVO) ---
print("--- Por favor, selecione as informações do registro ---")

registrante = questionary.text(
    "Qual o seu nome?",
    validate=lambda text: True if len(text) > 0 else "O nome é obrigatório. Por favor, tente novamente."
).ask().title()

turno = questionary.select(
    "Qual o seu turno?",
    choices=[
        "T1",
        "T2",
        "T3"
    ]
).ask()

print(f"\nObrigado, {registrante}! Iniciando a automação para o turno {turno}...\n")


# --- 1. CONFIGURAÇÃO DAS PASTAS E PARÂMETROS ---
print("--- INICIANDO ROBÔ DE CRUZAMENTO DE DADOS (VERSÃO FINAL) ---")

pasta_pedidos = r''
pasta_gb = r''
pasta_resultado = r''
pasta_lixeira = r''

# CONFIGURAÇÃO DO GOOGLE SHEETS
NOME_DA_PLANILHA_SHEETS = "J&T EXPRESS - EXPEDIDO MAS NÃO CHEGOU"
NOME_DA_ABA_SHEETS = "Consolidado"
ARQUIVO_DE_CREDENCIAL = 'credentials.json'

status_alvo = '中心发件'
linhas_por_arquivo = 500

# --- FUNÇÕES AUXILIARES ---

def carregar_planilhas_da_pasta(caminho_pasta, extensao_arquivo):
    padrao_busca = os.path.join(caminho_pasta, f'*.{extensao_arquivo}')
    lista_arquivos = glob.glob(padrao_busca)
    if not lista_arquivos:
        print(f"AVISO: Nenhum arquivo '.{extensao_arquivo}' encontrado na pasta: {caminho_pasta}")
        return pd.DataFrame(), []
    lista_de_dfs = []
    for arquivo in lista_arquivos:
        if os.path.basename(arquivo).startswith('~$'): continue
        print(f"  -> Lendo arquivo: {os.path.basename(arquivo)}")
        df_temp = pd.read_excel(arquivo, header=None)
        lista_de_dfs.append(df_temp)
    df_completo = pd.concat(lista_de_dfs, ignore_index=True) if lista_de_dfs else pd.DataFrame()
    return df_completo, lista_arquivos

def enviar_para_sheets(dataframe_para_enviar):
    try:
        print("\n[PASSO 6 de 7] Conectando ao Sheets...")
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(ARQUIVO_DE_CREDENCIAL, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open(NOME_DA_PLANILHA_SHEETS)
        worksheet = spreadsheet.worksheet(NOME_DA_ABA_SHEETS)
        print(f"  -> Conectado à planilha '{NOME_DA_PLANILHA_SHEETS}' e à aba '{NOME_DA_ABA_SHEETS}' com sucesso.")
        dataframe_para_enviar = dataframe_para_enviar.replace({np.nan: None})
        dados_para_adicionar = dataframe_para_enviar.values.tolist()
        primeira_linha = worksheet.row_values(1)
        if not primeira_linha:
            print("  -> Planilha vazia. Adicionando cabeçalho e dados...")
            cabecalho = [dataframe_para_enviar.columns.tolist()]
            dados_para_adicionar = cabecalho + dados_para_adicionar
            worksheet.update('A1', dados_para_adicionar, value_input_option='USER_ENTERED')
        else:
            print("  -> Planilha já contém dados. Adicionando apenas novos pedidos...")
            worksheet.append_rows(dados_para_adicionar, value_input_option='USER_ENTERED')
        print(f"SUCESSO: {len(dataframe_para_enviar)} pedidos foram adicionados à planilha.")
    except Exception as e:
        print(f"\nOcorreu um erro inesperado ao conectar com o Sheets: {e}")

def arquivar_arquivos_processados(arquivos_pedidos, arquivos_gb):
    try:
        print("\n[PASSO 7 de 7] Arquivando arquivos processados...")
        timestamp_lixeira = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pasta_destino_run = os.path.join(pasta_lixeira, timestamp_lixeira)
        pasta_destino_pedidos = os.path.join(pasta_destino_run, 'pedidos')
        pasta_destino_gb = os.path.join(pasta_destino_run, 'gb')
        os.makedirs(pasta_destino_pedidos)
        os.makedirs(pasta_destino_gb)
        print(f"  -> Pasta de arquivamento criada em: {pasta_destino_run}")
        for arquivo in arquivos_pedidos:
            shutil.move(arquivo, pasta_destino_pedidos)
        print(f"  -> {len(arquivos_pedidos)} arquivo(s) da pasta 'pedidos' foram arquivados.")
        for arquivo in arquivos_gb:
            shutil.move(arquivo, pasta_destino_gb)
        print(f"  -> {len(arquivos_gb)} arquivo(s) da pasta 'gb' foram arquivados.")
    except Exception as e:
        print(f"\nOcorreu um erro ao tentar arquivar os arquivos: {e}")


# --- FLUXO PRINCIPAL DO SCRIPT ---

# [PASSO 1 e 2] Carregamento e Limpeza
print(f"\n[PASSO 1 de 7] Carregando e limpando a base de 'pedidos'...")
df_pedidos, lista_arquivos_pedidos = carregar_planilhas_da_pasta(pasta_pedidos, 'xls')
if not df_pedidos.empty:
    linhas_antes = len(df_pedidos)
    df_pedidos = df_pedidos[~df_pedidos[0].astype(str).str.contains('-', na=False)]
    print(f"  -> Limpeza: {linhas_antes - len(df_pedidos)} pedidos com '-' foram desconsiderados.")

print(f"\n[PASSO 2 de 7] Carregando planilhas da pasta 'gb'...")
df_gb, lista_arquivos_gb = carregar_planilhas_da_pasta(pasta_gb, 'xlsx')

# [PASSO 3] Cruzamento dos dados
if df_pedidos.empty or df_gb.empty:
    print("\nERRO: Uma das fontes de dados está vazia ou foi zerada na limpeza.")
else:
    print("\n[PASSO 3 de 7] Aplicando a lógica de filtro e cruzamento...")
    df_gb_filtrado = df_gb[df_gb[1] == status_alvo].copy()
    if df_gb_filtrado.empty:
        print("  -> Nenhum pedido corresponde ao critério do status.")
    else:
        df_gb_para_merge = df_gb_filtrado[[0, 4, 78]].copy()
        df_gb_para_merge.columns = ['chave_A_gb', 'chave_E_gb', 'Regional_Sigla']
        df_resultado_final = pd.merge(df_pedidos, df_gb_para_merge, left_on=[0, 2], right_on=['chave_A_gb', 'chave_E_gb'], how='inner')
        print(f"SUCESSO: O cruzamento resultou em {len(df_resultado_final)} pedidos a serem exportados.")
        
        if len(df_resultado_final) > 0:
            horario_execucao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            # [PASSO 4] Preparação das 3 tabelas de saída diferentes
            print("\n[PASSO 4 de 7] Preparando os diferentes formatos de relatório...")
            df_base = pd.DataFrame({
                'PEDIDOS': df_resultado_final[0], 'Tipo de bipagem': 'Encomenda expedido mas não chegou (有发未到件)', 'Regional': df_resultado_final['Regional_Sigla'],
                'SC Destino': df_resultado_final[3], 'Base que escaneou': df_resultado_final['chave_E_gb'], 'Registrante': registrante,
                'Turno registrante': turno, 'horário de execução': horario_execucao, 'Status': 'Pendente de baixa'
            })
            df_base['SC Destino'] = df_base['SC Destino'].replace('SP BRE', 'SP - SÃO PAULO')
            df_base['Localização Mapa'] = df_base['Regional'].map(mapa_estados).fillna(df_base['Regional']) + ', Brazil'
            ordem_colunas_sheets = [
                'PEDIDOS', 'Tipo de bipagem', 'Regional', 'Localização Mapa', 'SC Destino', 'Base que escaneou', 'Registrante', 'Turno registrante', 'horário de execução', 'Status'
            ]
            df_para_sheets = df_base[ordem_colunas_sheets]
            df_consolidado_local = df_para_sheets.drop(columns=['Status'])
            df_para_arquivos_divididos = pd.DataFrame({
                'Número da carta de porte': df_resultado_final[0], 'operação': 'Transit', 'Primeiro nível codificação': 'N00',
                'Nível II codificação': 'N29', 'causa do problema': 'Sem recebimento no SC'
            })

            # [PASSO 5] Salvamento de arquivos locais
            print("\n[PASSO 5 de 7] Salvando os resultados locais...")
            timestamp_pasta = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            pasta_saida_final = os.path.join(pasta_resultado, timestamp_pasta)
            os.makedirs(pasta_saida_final, exist_ok=True)
            print(f"  -> Resultados locais serão salvos na pasta: {pasta_saida_final}")
            num_arquivos = math.ceil(len(df_para_arquivos_divididos) / linhas_por_arquivo)
            for i in range(num_arquivos):
                inicio = i * linhas_por_arquivo
                fim = inicio + linhas_por_arquivo
                df_pedaco = df_para_arquivos_divididos.iloc[inicio:fim]
                nome_arquivo = f"pedidos_filtrados_parte_{i+1}.xlsx"
                caminho_saida = os.path.join(pasta_saida_final, nome_arquivo)
                df_pedaco.to_excel(caminho_saida, index=False)
                print(f"    -> Arquivo dividido '{nome_arquivo}' (formato N00/N29) salvo.")
            caminho_consolidado_local = os.path.join(pasta_saida_final, "consolidado_geral.xlsx")
            df_consolidado_local.to_excel(caminho_consolidado_local, index=False)
            print(f"    -> Arquivo consolidado local 'consolidado_geral.xlsx' salvo.")

            # [PASSO 6] Enviar para o Sheets
            enviar_para_sheets(df_para_sheets)
        else:
            print("  -> Nenhum resultado a ser salvo ou enviado.")

# [PASSO 7] arquivamento dos arquivos de entrada
if lista_arquivos_pedidos or lista_arquivos_gb:
    arquivar_arquivos_processados(lista_arquivos_pedidos, lista_arquivos_gb)

print("\n--- PROCESSO FINALIZADO ---")
