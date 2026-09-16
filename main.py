from __future__ import annotations
import sqlite3
import urllib.parse
import io
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "locacoes.db"
LOGO_PATH = APP_DIR / "IMG_0207.png"
ATTACHED_LOGO_PATH = APP_DIR / "attached_assets" / "IMG_0207_1789499383772.png"

OBRAS = ["CASA RIMAR", "CASA IM", "REFORMA GV", "HBR"]

FORNECEDORES_PADRAO = [
    "Equipamento CM (Próprio)",
    "HL Locações",
    "Loc Express",
    "Escan",
    "Outro (especificar)"
]

MESES_NOMES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS locacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento TEXT NOT NULL,
                fornecedor TEXT NOT NULL,
                obra TEXT NOT NULL,
                data_retirada TEXT NOT NULL,
                data_devolucao TEXT NOT NULL,
                custo_diario REAL NOT NULL CHECK (custo_diario >= 0),
                status TEXT NOT NULL DEFAULT 'Ativa',
                data_baixa TEXT,
                tipo_origem TEXT DEFAULT 'Terceiros',
                custo_mensal REAL DEFAULT 0,
                limite_dias INTEGER DEFAULT 15
            )
            """
        )
        cursor = connection.execute("PRAGMA table_info(locacoes)")
        cols_loc = [col[1] for col in cursor.fetchall()]
        if "tipo_origem" not in cols_loc:
            connection.execute("ALTER TABLE locacoes ADD COLUMN tipo_origem TEXT DEFAULT 'Terceiros'")
        if "custo_mensal" not in cols_loc:
            connection.execute("ALTER TABLE locacoes ADD COLUMN custo_mensal REAL DEFAULT 0")
        if "limite_dias" not in cols_loc:
            connection.execute("ALTER TABLE locacoes ADD COLUMN limite_dias INTEGER DEFAULT 15")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS patrimonio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento TEXT NOT NULL UNIQUE,
                valor_aquisicao REAL NOT NULL DEFAULT 0,
                data_aquisicao TEXT NOT NULL,
                status_ativo TEXT NOT NULL DEFAULT 'Operacional',
                intervalo_manutencao_dias INTEGER DEFAULT 30,
                ultima_revisao TEXT,
                origem_equipamento TEXT DEFAULT 'Equipamento CM (Próprio)',
                diaria_padrao REAL DEFAULT 0,
                mensal_padrao REAL DEFAULT 0
            )
            """
        )
        cursor_pat = connection.execute("PRAGMA table_info(patrimonio)")
        cols_pat = [col[1] for col in cursor_pat.fetchall()]
        if "status_ativo" not in cols_pat:
            connection.execute("ALTER TABLE patrimonio ADD COLUMN status_ativo TEXT NOT NULL DEFAULT 'Operacional'")
        if "intervalo_manutencao_dias" not in cols_pat:
            connection.execute("ALTER TABLE patrimonio ADD COLUMN intervalo_manutencao_dias INTEGER DEFAULT 30")
        if "ultima_revisao" not in cols_pat:
            connection.execute("ALTER TABLE patrimonio ADD COLUMN ultima_revisao TEXT")
        if "origem_equipamento" not in cols_pat:
            connection.execute("ALTER TABLE patrimonio ADD COLUMN origem_equipamento TEXT DEFAULT 'Equipamento CM (Próprio)'")
        if "diaria_padrao" not in cols_pat:
            connection.execute("ALTER TABLE patrimonio ADD COLUMN diaria_padrao REAL DEFAULT 0")
        if "mensal_padrao" not in cols_pat:
            connection.execute("ALTER TABLE patrimonio ADD COLUMN mensal_padrao REAL DEFAULT 0")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS manutencoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento TEXT NOT NULL,
                tipo_evento TEXT NOT NULL,
                data_evento TEXT NOT NULL,
                custo REAL NOT NULL DEFAULT 0,
                motivo TEXT NOT NULL,
                prestador TEXT,
                status TEXT NOT NULL DEFAULT 'Concluído'
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cronograma_preventiva (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento TEXT NOT NULL,
                ano INTEGER NOT NULL,
                mes INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pendente',
                data_conclusao TEXT,
                observacoes TEXT,
                UNIQUE(equipamento, ano, mes)
            )
            """
        )
        connection.commit()


def load_rentals() -> pd.DataFrame:
    with get_connection() as connection:
        df = pd.read_sql_query(
            "SELECT * FROM locacoes ORDER BY date(data_devolucao), id DESC",
            connection,
        )
        if "tipo_origem" not in df.columns:
            df["tipo_origem"] = "Terceiros"
        if "custo_mensal" not in df.columns:
            df["custo_mensal"] = 0.0
        if "limite_dias" not in df.columns:
            df["limite_dias"] = 15
        return df


def load_patrimonio() -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query("SELECT * FROM patrimonio ORDER BY equipamento ASC", connection)


def update_patrimonio_completo(old_name: str, new_name: str, origem: str, val_compra: float, val_diaria: float, val_mensal: float, dt_aq: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE patrimonio
            SET equipamento = ?, origem_equipamento = ?, valor_aquisicao = ?, diaria_padrao = ?, mensal_padrao = ?, data_aquisicao = ?
            WHERE equipamento = ?
            """,
            (new_name.strip(), origem, val_compra, val_diaria, val_mensal, dt_aq, old_name)
        )
        if old_name != new_name.strip():
            conn.execute("UPDATE locacoes SET equipamento = ? WHERE equipamento = ?", (new_name.strip(), old_name))
            conn.execute("UPDATE manutencoes SET equipamento = ? WHERE equipamento = ?", (new_name.strip(), old_name))
            conn.execute("UPDATE cronograma_preventiva SET equipamento = ? WHERE equipamento = ?", (new_name.strip(), old_name))
        conn.commit()


def delete_patrimonio(nome_eq: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM patrimonio WHERE equipamento = ?", (nome_eq,))
        conn.commit()


def load_manutencoes() -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query("SELECT * FROM manutencoes ORDER BY date(data_evento) DESC, id DESC", connection)


def load_cronograma(ano: int) -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query("SELECT * FROM cronograma_preventiva WHERE ano = ?", connection, params=(ano,))


def agendar_manutencao_mes(equipamento: str, ano: int, mes: int, observacoes: str = "") -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO cronograma_preventiva (equipamento, ano, mes, status, observacoes)
            VALUES (?, ?, ?, 'Pendente', ?)
            ON CONFLICT(equipamento, ano, mes) DO UPDATE SET observacoes = excluded.observacoes
            """,
            (equipamento, ano, mes, observacoes),
        )
        connection.commit()


def concluir_manutencao_mes(cronograma_id: int, data_conclusao: date, custo: float = 0.0) -> None:
    with get_connection() as connection:
        cursor = connection.execute("SELECT equipamento, ano, mes FROM cronograma_preventiva WHERE id = ?", (cronograma_id,))
        item = cursor.fetchone()
        if item:
            equipamento, ano, mes = item[0], item[1], item[2]
            connection.execute(
                "UPDATE cronograma_preventiva SET status = 'Concluído', data_conclusao = ? WHERE id = ?",
                (data_conclusao.isoformat(), cronograma_id),
            )
            connection.execute(
                """
                INSERT INTO manutencoes (equipamento, tipo_evento, data_evento, custo, motivo, prestador)
                VALUES (?, 'Preventiva Concluída', ?, ?, ?, 'Equipe Interna CM')
                """,
                (equipamento, data_conclusao.isoformat(), custo, f"Manutenção Preventiva ref. ao mês {mes:02d}/{ano}"),
            )
            connection.execute(
                "UPDATE patrimonio SET ultima_revisao = ?, status_ativo = 'Operacional' WHERE equipamento = ?",
                (data_conclusao.isoformat(), equipamento),
            )
            connection.commit()


def registrar_evento_manutencao(equipamento: str, tipo_evento: str, data_evento: date, custo: float, motivo: str, prestador: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO manutencoes (equipamento, tipo_evento, data_evento, custo, motivo, prestador)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (equipamento.strip(), tipo_evento, data_evento.isoformat(), custo, motivo.strip(), prestador.strip()),
        )
        if tipo_evento == "Perda Total / Baixa":
            connection.execute("UPDATE patrimonio SET status_ativo = 'Baixado / Perda' WHERE equipamento = ?", (equipamento.strip(),))
        elif tipo_evento == "Conserto (Corretiva)":
            connection.execute("UPDATE patrimonio SET status_ativo = 'Em Oficina' WHERE equipamento = ?", (equipamento.strip(),))
        elif tipo_evento == "Preventiva Concluída":
            connection.execute("UPDATE patrimonio SET status_ativo = 'Operacional', ultima_revisao = ? WHERE equipamento = ?", (data_evento.isoformat(), equipamento.strip()))
        connection.commit()


def liberar_maquina_oficina(equipamento: str, data_liberacao: date) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE patrimonio SET status_ativo = 'Operacional', ultima_revisao = ? WHERE equipamento = ?",
            (data_liberacao.isoformat(), equipamento.strip())
        )
        connection.commit()


def create_rental(equipamento: str, fornecedor: str, tipo_origem: str, obra: str, data_retirada: date, data_devolucao: date, custo_diario: float, custo_mensal: float, limite_dias: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO locacoes
                (equipamento, fornecedor, tipo_origem, obra, data_retirada, data_devolucao, custo_diario, custo_mensal, limite_dias)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (equipamento.strip(), fornecedor.strip(), tipo_origem, obra.strip(), data_retirada.isoformat(), data_devolucao.isoformat(), custo_diario, custo_mensal, limite_dias),
        )
        connection.commit()


def close_rental(rental_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE locacoes SET status = 'Devolvida', data_baixa = ? WHERE id = ? AND status = 'Ativa'",
            (date.today().isoformat(), rental_id),
        )
        connection.commit()


def as_date(value: object) -> date:
    return pd.to_datetime(value).date()


def rental_days(row: pd.Series, reference_day: date | None = None) -> int:
    start = as_date(row["data_retirada"])
    today = reference_day or date.today()
    if row["status"] == "Devolvida" and pd.notna(row["data_baixa"]):
        end = as_date(row["data_baixa"])
    else:
        end = min(as_date(row["data_devolucao"]), today)
    return max(1, (end - start).days + 1)


def total_cost(row: pd.Series) -> float:
    days = rental_days(row)
    diario = float(row.get("custo_diario", 0.0))
    mensal = float(row.get("custo_mensal", 0.0))
    limite = int(row.get("limite_dias", 15))

    if mensal > 0:
        meses_cheios = days // 30
        dias_sobra = days % 30
        if dias_sobra >= limite:
            meses_cheios += 1
            dias_sobra = 0
        return (meses_cheios * mensal) + (dias_sobra * diario)
    return days * diario


def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_date(value: object) -> str:
    if pd.isna(value) or not value:
        return "-"
    return as_date(value).strftime("%d/%m/%Y")


def deadline_label(row: pd.Series) -> str:
    days = (as_date(row["data_devolucao"]) - date.today()).days
    if days < 0:
        return f"Atrasado {abs(days)} dia(s)"
    if days == 0:
        return "Vence hoje"
    return f"{days} dia(s) restante(s)"


def logo_path() -> Path | None:
    if LOGO_PATH.exists():
        return LOGO_PATH
    if ATTACHED_LOGO_PATH.exists():
        return ATTACHED_LOGO_PATH
    return None


def gerar_link_whatsapp(telefone: str, mensagem: str) -> str:
    clean_tel = "".join([c for c in telefone if c.isdigit()])
    msg_encoded = urllib.parse.quote(mensagem)
    return f"https://api.whatsapp.com/send?phone={clean_tel}&text={msg_encoded}"


def gerar_link_google_agenda(equipamento: str, ano: int, mes: int, obs: str) -> str:
    hoje = date.today()
    if hoje.year == ano and hoje.month == mes:
        data_evento = hoje + timedelta(days=1)
    else:
        try:
            data_evento = date(ano, mes, 5)
        except ValueError:
            data_evento = hoje
    d1 = data_evento.strftime("%Y%m%d")
    d2 = (data_evento + timedelta(days=1)).strftime("%Y%m%d")
    titulo = f"🔧 Manutenção CM: {equipamento}"
    detalhes = f"Manutenção Preventiva programada para o mês {mes:02d}/{ano}.\n\nObs/Tarefas: {obs}\n\nAcesse o sistema CM Rental após realizar para dar baixa."
    return f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={urllib.parse.quote(titulo)}&dates={d1}/{d2}&details={urllib.parse.quote(detalhes)}"


# ==== SISTEMA DE EXPORTAÇÃO EXCEL/PDF ====
def export_buttons(df: pd.DataFrame, filename_prefix: str, titulo_pdf: str) -> None:
    st.write("") 
    c1, c2, c3 = st.columns([1.5, 1.5, 3])
    
    # Gerar Excel
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Relatorio')
        excel_data = output.getvalue()
        
        c1.download_button(
            label="📊 Baixar Excel",
            data=excel_data,
            file_name=f"{filename_prefix}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    except Exception as e:
        c1.error("Excel indisponível (atualize requirements.txt)")
    
    # Gerar PDF
    try:
        from fpdf import FPDF
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        safe_titulo = titulo_pdf.encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(0, 10, safe_titulo, ln=True, align='C')
        pdf.ln(5)
        
        pdf.set_font("Arial", 'B', 9)
        printable_width = 277
        num_cols = len(df.columns)
        base_width = printable_width / num_cols if num_cols > 0 else printable_width
        row_height = 7
        
        # Cabeçalho
        for col in df.columns:
            safe_col = str(col).encode('latin-1', 'replace').decode('latin-1')[:30]
            pdf.cell(base_width, row_height, safe_col, border=1, align='C')
        pdf.ln(row_height)
        
        # Linhas
        pdf.set_font("Arial", '', 8)
        for _, row in df.iterrows():
            for item in row:
                safe_item = str(item).encode('latin-1', 'replace').decode('latin-1')[:35]
                pdf.cell(base_width, row_height, safe_item, border=1)
            pdf.ln(row_height)
            
        pdf_data = pdf.output(dest='S').encode('latin-1')
        
        c2.download_button(
            label="📄 Baixar PDF",
            data=pdf_data,
            file_name=f"{filename_prefix}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    except ImportError:
        c2.error("PDF indisponível (atualize requirements.txt)")


def render_sidebar() -> str:
    img = logo_path()
    if img:
        st.sidebar.image(str(img), use_container_width=True)
    st.sidebar.markdown("### CM Rental")
    st.sidebar.caption("Gestão Integrada de Frotas & Locações")
    st.sidebar.divider()
    menu = st.sidebar.radio(
        "Menu Principal",
        [
            "Cadastro de Equipamentos",
            "Nova Locação (Despacho)",
            "Equipamentos Alugados",
            "Plano Anual de Manutenção",
            "Manutenção & Sinistros",
            "Patrimônio & Lucro por Máquina",
            "Resultado Mensal & Payback",
            "Dashboard Geral",
        ],
    )
    st.sidebar.divider()
    rentals = load_rentals()
    active_count = int((rentals["status"] == "Ativa").sum()) if not rentals.empty else 0
    st.sidebar.metric("Locações ativas", active_count)
    st.sidebar.divider()
    st.sidebar.markdown("👤 **Guilherme Macedo de Araújo Matias da Costa**")
    st.sidebar.caption("Diretoria CM Rental")
    return menu


def render_cadastro_equipamentos() -> None:
    st.title("Cadastro de Equipamentos (Estoque)")
    st.write("Registre e gerencie o maquinário próprio (CM) ou de locadoras parceiras.")

    with st.form("form_cad_eq", clear_on_submit=True):
        st.subheader("Inserir Novo Equipamento")
        c1, c2 = st.columns(2)
        with c1:
            nome_eq = st.text_input("Identificação / Nome", placeholder="Ex.: Betoneira 400L 01")
            origem_sel = st.selectbox("Origem / Proprietário", FORNECEDORES_PADRAO)
            fornecedor_custom = ""
            if origem_sel == "Outro (especificar)":
                fornecedor_custom = st.text_input("Nome do parceiro/fornecedor:")
        with c2:
            val_compra = st.number_input("Valor de Compra (R$) - Preencha apenas se for CM", min_value=0.0, step=100.0, format="%.2f")
            val_diaria = st.number_input("Valor Padrão da Diária (R$)", min_value=0.0, step=5.0, format="%.2f")
            val_mensal = st.number_input("Valor Padrão Mensal (R$)", min_value=0.0, step=50.0, format="%.2f")
            dt_aq = st.date_input("Data de Aquisição / Entrada", format="DD/MM/YYYY")

        sub = st.form_submit_button("Salvar no Estoque", type="primary", use_container_width=True)
        if sub:
            if not nome_eq.strip():
                st.error("Por favor, preencha a identificação do equipamento.")
            else:
                forn_final = fornecedor_custom.strip() if origem_sel == "Outro (especificar)" else origem_sel
                try:
                    with get_connection() as conn:
                        conn.execute(
                            """
                            INSERT INTO patrimonio 
                            (equipamento, valor_aquisicao, data_aquisicao, status_ativo, intervalo_manutencao_dias, origem_equipamento, diaria_padrao, mensal_padrao)
                            VALUES (?, ?, ?, 'Operacional', 30, ?, ?, ?)
                            """,
                            (nome_eq.strip(), val_compra, dt_aq.isoformat(), forn_final, val_diaria, val_mensal)
                        )
                        conn.commit()
                    st.success(f"Equipamento '{nome_eq}' cadastrado com sucesso!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Erro: Já existe um equipamento cadastrado com esse nome exato.")

    st.divider()
    st.subheader("Lista de Equipamentos Cadastrados")
    df_eq = load_patrimonio()
    
    if not df_eq.empty:
        show_df = df_eq[["equipamento", "origem_equipamento", "status_ativo", "diaria_padrao", "mensal_padrao", "valor_aquisicao"]].copy()
        show_df.columns = ["Equipamento", "Origem/Dono", "Status", "Diária (R$)", "Mensal (R$)", "Custo Aquisição (R$)"]
        
        # Botões de Exportação
        export_buttons(show_df, "estoque_cm_rental", "Relatório de Estoque e Patrimônio - CM Rental")
        
        show_df["Diária (R$)"] = show_df["Diária (R$)"].map(format_currency)
        show_df["Mensal (R$)"] = show_df["Mensal (R$)"].map(format_currency)
        show_df["Custo Aquisição (R$)"] = show_df["Custo Aquisição (R$)"].map(format_currency)
        st.dataframe(show_df, hide_index=True, use_container_width=True)
        
        st.write("")
        with st.expander("✏️ Editar ou Excluir Equipamento"):
            st.info("Atenção: ao alterar o nome de um equipamento, ele será atualizado em todo o histórico de locações.")
            eq_selecionado = st.selectbox("Selecione a máquina para alterar:", df_eq["equipamento"].tolist())
            linha = df_eq[df_eq["equipamento"] == eq_selecionado].iloc[0]
            
            c_ed1, c_ed2 = st.columns(2)
            with c_ed1:
                novo_nome = st.text_input("Nome", value=linha["equipamento"])
                nova_origem = st.selectbox(
                    "Origem", 
                    FORNECEDORES_PADRAO + [linha["origem_equipamento"]], 
                    index=0 if linha["origem_equipamento"] not in FORNECEDORES_PADRAO else FORNECEDORES_PADRAO.index(linha["origem_equipamento"])
                )
                novo_val_compra = st.number_input("Valor de Compra", value=float(linha["valor_aquisicao"]), format="%.2f")
            with c_ed2:
                nova_diaria = st.number_input("Diária Pad.", value=float(linha.get("diaria_padrao", 0.0)), format="%.2f")
                novo_mensal = st.number_input("Mensal Pad.", value=float(linha.get("mensal_padrao", 0.0)), format="%.2f")
                nova_data = st.date_input("Data Aq.", value=as_date(linha["data_aquisicao"]), format="DD/MM/YYYY")

            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1:
                if st.button("Salvar Alterações", type="primary", use_container_width=True):
                    update_patrimonio_completo(eq_selecionado, novo_nome, nova_origem, novo_val_compra, nova_diaria, novo_mensal, nova_data.isoformat())
                    st.success("Equipamento atualizado com sucesso!")
                    st.rerun()
            with col_btn2:
                if st.button("Excluir Equipamento", use_container_width=True):
                    delete_patrimonio(eq_selecionado)
                    st.success("Equipamento removido do estoque!")
                    st.rerun()
    else:
        st.info("Nenhum equipamento registrado ainda.")


def render_new_rental() -> None:
    st.title("Nova Locação (Despacho)")
    st.write("Despache um equipamento do seu estoque para a obra.")

    df_eq = load_patrimonio()
    if df_eq.empty:
        st.warning("⚠️ Seu estoque está vazio! Vá primeiro na aba 'Cadastro de Equipamentos' para registrar as máquinas.")
        return
        
    disponiveis = df_eq[df_eq["status_ativo"] == "Operacional"]
    if disponiveis.empty:
        st.warning("Nenhum equipamento operacional disponível no momento.")
        return

    st.subheader("1. Selecione o Equipamento")
    eq_selecionado = st.selectbox("Máquina Disponível no Estoque:", disponiveis["equipamento"].tolist())
    
    linha_eq = disponiveis[disponiveis["equipamento"] == eq_selecionado].iloc[0]
    origem_eq = linha_eq["origem_equipamento"]
    diaria_pad = float(linha_eq.get("diaria_padrao", 0.0))
    mensal_pad = float(linha_eq.get("mensal_padrao", 0.0))

    with st.form("new_rental_form", clear_on_submit=True):
        st.info(f"📌 **Origem/Proprietário:** {origem_eq}")
        c1, c2 = st.columns(2)
        with c1:
            obra = st.selectbox("Obra / Destino", OBRAS)
            data_retirada = st.date_input("Data de Saída / Retirada", value=date.today(), format="DD/MM/YYYY")
        with c2:
            data_devolucao = st.date_input("Previsão de Devolução", value=date.today() + timedelta(days=7), format="DD/MM/YYYY")
        
        st.subheader("2. Regimes e Valores de Cobrança")
        c3, c4, c5 = st.columns(3)
        with c3:
            custo_diario = st.number_input("Diária (R$)", value=diaria_pad, step=5.0, format="%.2f")
        with c4:
            custo_mensal = st.number_input("Mensal (R$)", value=mensal_pad, step=50.0, format="%.2f")
        with c5:
            limite_dias = st.number_input("Dias p/ virar mês cheio", min_value=1, max_value=30, value=15)
        
        submit = st.form_submit_button("Despachar Equipamento", type="primary", use_container_width=True)

    if submit:
        if data_devolucao < data_retirada:
            st.error("A data de devolução deve ser igual ou posterior à retirada.")
        else:
            tipo_origem = "Próprio (CM)" if origem_eq == "Equipamento CM (Próprio)" else "Terceiros"
            create_rental(
                equipamento=eq_selecionado,
                fornecedor=origem_eq,
                tipo_origem=tipo_origem,
                obra=obra,
                data_retirada=data_retirada,
                data_devolucao=data_devolucao,
                custo_diario=custo_diario,
                custo_mensal=custo_mensal,
                limite_dias=int(limite_dias),
            )
            st.success(f"Equipamento '{eq_selecionado}' despachado para {obra} com sucesso!")
            st.rerun()


def render_active_rentals() -> None:
    st.title("Equipamentos Alugados / Em Obra")
    st.write("Acompanhe as máquinas alocadas separadas por obra e o valor que cada frente está consumindo/faturando.")

    rentals = load_rentals()
    active = rentals[rentals["status"] == "Ativa"].copy()
    if active.empty:
        st.info("Nenhum equipamento em campo no momento.")
        return

    active["custo_numero"] = active.apply(total_cost, axis=1)
    overdue_count = sum(as_date(row["data_devolucao"]) < date.today() for _, row in active.iterrows())
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total de Máquinas em Uso", len(active))
    m2.metric("Próprios CM", int((active["tipo_origem"] == "Próprio (CM)").sum()))
    m3.metric("Terceiros", int((active["tipo_origem"] == "Terceiros").sum()))
    m4.metric("Devoluções em Atraso", overdue_count)

    # Preparar DataFrame consolidado para exportação
    df_export = active[["equipamento", "origem", "fornecedor", "obra", "data_retirada", "data_devolucao", "custo_numero"]].copy() if "origem" in active.columns else active[["equipamento", "tipo_origem", "fornecedor", "obra", "data_retirada", "data_devolucao", "custo_numero"]].copy()
    df_export.columns = ["Equipamento", "Origem", "Fornecedor", "Obra", "Retirada", "Devolucao", "Custo Acumulado (R$)"]
    export_buttons(df_export, "equipamentos_em_obra", "Relatório de Equipamentos em Obra")

    st.divider()

    obras_ativas = active["obra"].unique()
    for obra in obras_ativas:
        df_obra = active[active["obra"] == obra].copy()
        total_obra = df_obra["custo_numero"].sum()
        
        with st.expander(f"🏗️ Obra: {obra} | Custo Acumulado Atual: {format_currency(total_obra)}", expanded=True):
            df_show = df_obra[["id", "equipamento", "tipo_origem", "fornecedor", "data_retirada", "data_devolucao"]].copy()
            df_show["Custo"] = df_obra["custo_numero"].map(format_currency)
            df_show["Prazo"] = df_obra.apply(deadline_label, axis=1)
            
            df_show.columns = ["ID", "Equipamento", "Origem", "Fornecedor", "Retirada", "Devolução", "Custo", "Prazo"]
            df_show["Retirada"] = df_show["Retirada"].map(format_date)
            df_show["Devolução"] = df_show["Devolução"].map(format_date)
            
            st.dataframe(df_show, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("Dar Baixa em Devolução")
    rental_options = {
        f'#{row["id"]} · {row["equipamento"]} ({row["fornecedor"]}) · {row["obra"]}': int(row["id"])
        for _, row in active.iterrows()
    }
    selected_label = st.selectbox("Selecione a locação encerrada para desmobilizar:", list(rental_options.keys()))
    if st.button("Confirmar Devolução", type="primary"):
        close_rental(rental_options[selected_label])
        st.success("Equipamento desmobilizado com sucesso!")
        st.rerun()


def render_plano_anual() -> None:
    st.title("Plano Anual de Manutenção Preventiva")
    st.write("Visão em planilha anual do plano de revisões periódicas da frota própria CM.")

    patrimonio_df = load_patrimonio()
    pat_cm = patrimonio_df[patrimonio_df["origem_equipamento"] == "Equipamento CM (Próprio)"]
    
    if pat_cm.empty:
        st.info("Nenhum equipamento próprio CM cadastrado no estoque ainda.")
        return

    equipamentos_ativos = pat_cm[pat_cm["status_ativo"] != "Baixado / Perda"]["equipamento"].tolist()

    ano_atual = date.today().year
    mes_atual = date.today().month
    ano_sel = st.selectbox("Ano de Referência do Plano", [ano_atual, ano_atual + 1], index=0)

    with st.expander("📅 Agendar ou Programar Manutenção para um Mês"):
        c1, c2, c3 = st.columns([2, 1, 2])
        with c1:
            eq_agendar = st.selectbox("Equipamento CM:", equipamentos_ativos)
        with c2:
            mes_agendar = st.selectbox("Mês Programado:", range(1, 13), format_func=lambda m: MESES_NOMES[m - 1], index=mes_atual - 1)
        with c3:
            obs_agendar = st.text_input("Observação / Itens a revisar:", placeholder="Troca de óleo, checagem elétrica")
        
        if st.button("Gravar no Plano", type="primary"):
            agendar_manutencao_mes(eq_agendar, ano_sel, mes_agendar, obs_agendar)
            st.success(f"Manutenção de {eq_agendar} programada para {MESES_NOMES[mes_agendar - 1]}/{ano_sel}!")
            st.rerun()

    cronograma_df = load_cronograma(ano_sel)

    st.subheader(f"Planilha de Manutenções Preventivas - {ano_sel}")
    matriz_dados = []
    for eq in equipamentos_ativos:
        linha = {"Equipamento": eq}
        for m in range(1, 13):
            nome_col = MESES_NOMES[m - 1][:3]
            sub = cronograma_df[(cronograma_df["equipamento"] == eq) & (cronograma_df["mes"] == m)]
            if sub.empty:
                linha[nome_col] = "-"
            else:
                stt = sub.iloc[0]["status"]
                if stt == "Concluído":
                    linha[nome_col] = "🟢 OK"
                elif ano_sel == ano_atual and m < mes_atual:
                    linha[nome_col] = "🔴 Atrasada"
                elif ano_sel == ano_atual and m == mes_atual:
                    linha[nome_col] = "🟡 Vence este mês"
                else:
                    linha[nome_col] = "📅 Agendada"
        matriz_dados.append(linha)

    df_matriz = pd.DataFrame(matriz_dados)
    
    export_buttons(df_matriz, f"plano_manutencao_{ano_sel}", f"Plano de Manutenção Preventiva - {ano_sel}")
    st.dataframe(df_matriz, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader(f"⚠️ Lembretes de Manutenção e Cobrança ({MESES_NOMES[mes_atual - 1]}/{ano_atual})")

    pendencias = cronograma_df[
        (cronograma_df["status"] == "Pendente") &
        (cronograma_df["ano"] == ano_atual) &
        (cronograma_df["mes"] <= mes_atual)
    ].copy()

    if pendencias.empty:
        st.success("🎉 Nenhuma manutenção preventiva atrasada ou pendente para este mês!")
    else:
        st.warning(f"Existem **{len(pendencias)} manutenção(ões)** pendentes de execução!")
        tel_cobranca = st.text_input("WhatsApp do Encarregado (com DDD):", value="5584999999999")

        for _, item in pendencias.iterrows():
            c_card1, c_card2, c_card3, c_card4 = st.columns([2.5, 1, 1, 1.2])
            is_atrasada = item["mes"] < mes_atual
            rotulo_status = f"🔴 ATRASADA (Era p/ {MESES_NOMES[item['mes'] - 1]})" if is_atrasada else "🟡 VENCE ESTE MÊS"

            with c_card1:
                st.markdown(f"**{item['equipamento']}** — {rotulo_status}")
                if item["observacoes"]:
                    st.caption(f"Obs: {item['observacoes']}")
            
            with c_card2:
                if st.button(f"✅ Dar Baixa #{item['id']}", key=f"btn_done_{item['id']}"):
                    concluir_manutencao_mes(int(item["id"]), date.today(), custo=0.0)
                    st.success("Manutenção concluída com sucesso!")
                    st.rerun()

            with c_card3:
                msg = (
                    f"Olá! Lembrete operacional da CM Rental:\n\n"
                    f"A *{item['equipamento']}* está com a Preventiva de *{MESES_NOMES[item['mes'] - 1]}/{item['ano']}* pendente.\n"
                    f"Favor providenciar a revisão o quanto antes."
                )
                link_wa = gerar_link_whatsapp(tel_cobranca, msg)
                st.link_button("📲 Cobrar WPP", link_wa)
                
            with c_card4:
                link_agenda = gerar_link_google_agenda(item['equipamento'], item['ano'], item['mes'], item['observacoes'] or "")
                st.link_button("📅 Criar Alerta", link_agenda, help="Salva no seu Google Agenda.")


def render_manutencoes() -> None:
    st.title("Manutenção, Consertos e Perdas")
    st.write("Registre sinistros, quebras, envios para conserto e perdas materiais da frota CM.")

    patrimonio_df = load_patrimonio()
    pat_cm = patrimonio_df[patrimonio_df["origem_equipamento"] == "Equipamento CM (Próprio)"]
    
    if pat_cm.empty:
        st.warning("Cadastre primeiro os equipamentos na aba 'Cadastro de Equipamentos'.")
        return

    na_oficina = pat_cm[pat_cm["status_ativo"] == "Em Oficina"]
    if not na_oficina.empty:
        with st.expander("🛠️ Máquinas Atualmente em Conserto / Na Oficina", expanded=True):
            st.info("Libere as máquinas que voltaram da oficina para poderem ser locadas novamente:")
            c_of1, c_of2, c_of3 = st.columns([2, 1, 1])
            with c_of1:
                eq_lib = st.selectbox("Equipamento pronto:", na_oficina["equipamento"].tolist())
            with c_of2:
                dt_lib = st.date_input("Data do Retorno:", value=date.today(), format="DD/MM/YYYY")
            with c_of3:
                st.write("")
                st.write("")
                if st.button("Liberar para Locação", type="primary"):
                    liberar_maquina_oficina(eq_lib, dt_lib)
                    st.success(f"{eq_lib} retornou da oficina e está operacional!")
                    st.rerun()

    with st.form("form_sinistro", clear_on_submit=True):
        st.subheader("Registrar Ocorrência / Conserto / Perda")
        col1, col2 = st.columns(2)
        with col1:
            eq_alvo = st.selectbox("Equipamento CM", pat_cm["equipamento"].tolist())
            tipo_ev = st.selectbox(
                "Tipo de Ocorrência",
                [
                    "Conserto (Corretiva)",
                    "Preventiva Concluída",
                    "Perda Total / Baixa",
                ],
            )
            data_ev = st.date_input("Data do Ocorrido / Registro", value=date.today(), format="DD/MM/YYYY")
            
        with col2:
            custo_ev = st.number_input("Custo Total da Manutenção/Conserto (R$)", min_value=0.0, step=50.0, format="%.2f")
            prestador = st.text_input("Oficina / Prestador de Serviço", placeholder="Ex.: Motores & Cia, Oficina HL, Interno")
            motivo = st.text_area(
                "Diagnóstico / O que aconteceu?",
                placeholder="Ex.: Motor queimou por trabalhar em 220V em tomada errada; Troca de rolamentos e induzido.",
            )

        submit_ev = st.form_submit_button("Lançar Ocorrência", type="primary", use_container_width=True)
        if submit_ev:
            if not motivo.strip():
                st.error("É obrigatório detalhar o que aconteceu (motivo/diagnóstico).")
            else:
                registrar_evento_manutencao(
                    equipamento=eq_alvo,
                    tipo_evento=tipo_ev,
                    data_evento=data_ev,
                    custo=custo_ev,
                    motivo=motivo,
                    prestador=prestador,
                )
                st.success(f"Evento registrado com sucesso para {eq_alvo}!")
                st.rerun()

    st.divider()
    st.subheader("Histórico Geral de Consertos e Sinistros")
    hist_manut = load_manutencoes()
    if hist_manut.empty:
        st.info("Nenhuma ocorrência registrada até o momento.")
    else:
        df_show = hist_manut.copy()
        total_gasto_oficina = df_show["custo"].sum()
        st.metric("Total Gasto em Manutenções e Consertos", format_currency(total_gasto_oficina))
        
        df_show["data_evento"] = df_show["data_evento"].map(format_date)
        df_show["custo"] = df_show["custo"].map(format_currency)
        df_show.columns = ["ID", "Equipamento", "Tipo", "Data", "Custo", "Motivo / Diagnóstico", "Oficina/Prestador", "Status"]
        st.dataframe(df_show, hide_index=True, use_container_width=True)


def render_patrimonio_lucro() -> None:
    st.title("Patrimônio & Lucro Real por Máquina")
    st.write("Visão financeira individual: DRE da máquina.")

    patrimonio_df = load_patrimonio()
    pat_cm = patrimonio_df[patrimonio_df["origem_equipamento"] == "Equipamento CM (Próprio)"]

    if pat_cm.empty:
        st.info("Nenhum equipamento próprio CM registrado no estoque ainda.")
        return

    locacoes_df = load_rentals()
    locacoes_df["custo_total"] = locacoes_df.apply(total_cost, axis=1)
    ganhos = locacoes_df[locacoes_df["tipo_origem"] == "Próprio (CM)"].groupby("equipamento")["custo_total"].sum().reset_index()
    ganhos.rename(columns={"custo_total": "faturamento_bruto"}, inplace=True)

    manut_df = load_manutencoes()
    gastos_oficina = manut_df.groupby("equipamento")["custo"].sum().reset_index()
    gastos_oficina.rename(columns={"custo": "custo_manutencoes"}, inplace=True)

    dre_maquinas = pd.merge(pat_cm, ganhos, on="equipamento", how="left").fillna(0.0)
    dre_maquinas = pd.merge(dre_maquinas, gastos_oficina, on="equipamento", how="left").fillna(0.0)

    dre_maquinas["lucro_operacional"] = dre_maquinas["faturamento_bruto"] - dre_maquinas["custo_manutencoes"]
    dre_maquinas["saldo_payback"] = dre_maquinas["lucro_operacional"] - dre_maquinas["valor_aquisicao"]

    total_patrimonio = float(dre_maquinas["valor_aquisicao"].sum())
    total_faturado = float(dre_maquinas["faturamento_bruto"].sum())
    total_gasto_manut = float(dre_maquinas["custo_manutencoes"].sum())
    lucro_liquido_total = total_faturado - total_gasto_manut

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Valor Total da Frota", format_currency(total_patrimonio))
    m2.metric("Faturamento Acumulado", format_currency(total_faturado))
    m3.metric("Gastos com Oficinas/Conserto", format_currency(total_gasto_manut))
    m4.metric("Resultado Líquido Real", format_currency(lucro_liquido_total))

    st.subheader("DRE Individual por Equipamento CM")
    
    def rotulo_resultado(row: pd.Series) -> str:
        if row["status_ativo"] == "Baixado / Perda":
            return "⚫ Baixado / Perda"
        if row["valor_aquisicao"] == 0:
            return "⚪ Sem valor de compra"
        if row["saldo_payback"] >= 0:
            return "🟢 100% Pago (Gerando Lucro)"
        if row["lucro_operacional"] > 0:
            return "🟡 Pagando o Investimento"
        return "🔴 Operando no Prejuízo"

    dre_maquinas["Resultado Financeiro"] = dre_maquinas.apply(rotulo_resultado, axis=1)

    tabela_show = dre_maquinas[[
        "equipamento", "status_ativo", "valor_aquisicao", "faturamento_bruto", "custo_manutencoes", "lucro_operacional", "saldo_payback", "Resultado Financeiro"
    ]].copy()
    tabela_show.columns = [
        "Equipamento", "Status", "Valor Compra", "Faturado", "Custos Conserto", "Lucro Operacional", "Saldo Final", "Desempenho"
    ]
    
    export_buttons(tabela_show, "dre_maquinas_cm", "DRE - Patrimonio e Lucro por Maquina CM")
    
    tabela_show["Valor Compra"] = tabela_show["Valor Compra"].map(format_currency)
    tabela_show["Faturado"] = tabela_show["Faturado"].map(format_currency)
    tabela_show["Custos Conserto"] = tabela_show["Custos Conserto"].map(format_currency)
    tabela_show["Lucro Operacional"] = tabela_show["Lucro Operacional"].map(format_currency)
    tabela_show["Saldo Final"] = tabela_show["Saldo Final"].map(format_currency)

    st.dataframe(tabela_show, hide_index=True, use_container_width=True)


def render_resultado_mensal() -> None:
    st.title("Resultado Mensal & Faturamento")
    st.write("Análise temporal mês a mês dos gastos por obra e rentabilidade da CM Rental.")

    rentals = load_rentals()
    if rentals.empty:
        st.info("Nenhuma locação registrada.")
        return

    rentals["dias_cobrados"] = rentals.apply(rental_days, axis=1)
    rentals["custo_total"] = rentals.apply(total_cost, axis=1)
    rentals["ano_mes"] = pd.to_datetime(rentals["data_retirada"]).dt.strftime("%Y-%m")

    st.subheader("1. Gasto com Locações por Obra (Mês a Mês)")
    gastos_obra_mes = rentals.pivot_table(
        index="ano_mes",
        columns="obra",
        values="custo_total",
        aggfunc="sum",
        fill_value=0.0,
    )
    
    tabela_obra = gastos_obra_mes.copy()
    export_buttons(tabela_obra.reset_index(), "gastos_mensais_obras", "Relatório Mensal de Gastos por Obra")
    
    st.bar_chart(gastos_obra_mes)

    for col in tabela_obra.columns:
        tabela_obra[col] = tabela_obra[col].map(format_currency)
    st.dataframe(tabela_obra, use_container_width=True)

    st.divider()

    st.subheader("2. Faturamento Mensal Gerado pela Frota CM")
    cm_rentals = rentals[rentals["tipo_origem"] == "Próprio (CM)"]
    if not cm_rentals.empty:
        fat_mensal_cm = cm_rentals.groupby("ano_mes")["custo_total"].sum().to_frame("Faturamento CM")
        st.line_chart(fat_mensal_cm, color="#2CA02C")
        
        t_fat = fat_mensal_cm.copy()
        t_fat["Faturamento CM"] = t_fat["Faturamento CM"].map(format_currency)
        st.dataframe(t_fat, use_container_width=True)
    else:
        st.info("Ainda não há locações de equipamentos próprios registradas.")


def render_dashboard() -> None:
    st.title("Dashboard Consolidado")
    st.write("Visão panorâmica da operação da CM Rental.")

    rentals = load_rentals()
    if rentals.empty:
        st.info("Cadastre uma locação para inicializar os indicadores.")
        return

    rentals["dias_cobrados"] = rentals.apply(rental_days, axis=1)
    rentals["custo_total"] = rentals.apply(total_cost, axis=1)

    total_op = float(rentals["custo_total"].sum())
    terceiros = float(rentals[rentals["tipo_origem"] == "Terceiros"]["custo_total"].sum())
    proprio = float(rentals[rentals["tipo_origem"] == "Próprio (CM)"]["custo_total"].sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Custo Total em Obra", format_currency(total_op))
    c2.metric("Locações de Terceiros (Desembolso)", format_currency(terceiros))
    c3.metric("Faturamento Frota Própria (CM)", format_currency(proprio))

    st.divider()
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.subheader("Gasto de Locações por Obra")
        by_work = (
            rentals.groupby("obra")["custo_total"]
            .sum()
            .sort_values(ascending=False)
            .to_frame("Custo Total")
        )
        st.bar_chart(by_work, color="#F35A24")

    with col_g2:
        st.subheader("Volume por Fornecedor")
        by_supplier = (
            rentals.groupby("fornecedor")["custo_total"]
            .sum()
            .sort_values(ascending=False)
            .to_frame("Custo Total")
        )
        st.bar_chart(by_supplier, color="#1F77B4")


def main() -> None:
    st.set_page_config(
        page_title="CM Rental | Gestão de Equipamentos",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_db()
    menu = render_sidebar()

    if menu == "Cadastro de Equipamentos":
        render_cadastro_equipamentos()
    elif menu == "Nova Locação (Despacho)":
        render_new_rental()
    elif menu == "Equipamentos Alugados":
        render_active_rentals()
    elif menu == "Plano Anual de Manutenção":
        render_plano_anual()
    elif menu == "Manutenção & Sinistros":
        render_manutencoes()
    elif menu == "Patrimônio & Lucro por Máquina":
        render_patrimonio_lucro()
    elif menu == "Resultado Mensal & Payback":
        render_resultado_mensal()
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
