from __future__ import annotations
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "locacoes.db"
LOGO_PATH = APP_DIR / "IMG_0207.png"
ATTACHED_LOGO_PATH = APP_DIR / "attached_assets" / "IMG_0207_1789499383772.png"

# Lista de obras ativas
OBRAS = ["CASA RIMAR", "CASA IM", "REFORMA GV", "HBR"]

# Origens/Fornecedores pré-definidos
FORNECEDORES_PADRAO = [
    "Equipamento CM (Próprio)",
    "HL Locações",
    "Loc Express",
    "Escan",
    "Outro (especificar)"
]


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        # Tabela de Locações
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
        # Atualização automática do banco (Migrations)
        cursor = connection.execute("PRAGMA table_info(locacoes)")
        colunas = [col[1] for col in cursor.fetchall()]
        if "tipo_origem" not in colunas:
            connection.execute("ALTER TABLE locacoes ADD COLUMN tipo_origem TEXT DEFAULT 'Terceiros'")
        if "custo_mensal" not in colunas:
            connection.execute("ALTER TABLE locacoes ADD COLUMN custo_mensal REAL DEFAULT 0")
        if "limite_dias" not in colunas:
            connection.execute("ALTER TABLE locacoes ADD COLUMN limite_dias INTEGER DEFAULT 15")
            
        # Nova Tabela de Patrimônio (Equipamentos da Empresa)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS patrimonio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento TEXT NOT NULL UNIQUE,
                valor_aquisicao REAL NOT NULL DEFAULT 0,
                data_aquisicao TEXT NOT NULL
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
        # Garantia de retrocompatibilidade para dados antigos
        if "tipo_origem" not in df.columns:
            df["tipo_origem"] = "Terceiros"
        if "custo_mensal" not in df.columns:
            df["custo_mensal"] = 0.0
        if "limite_dias" not in df.columns:
            df["limite_dias"] = 15
        return df


def load_patrimonio() -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query("SELECT * FROM patrimonio ORDER BY id DESC", connection)


def create_patrimonio(equipamento: str, valor: float, data_aquisicao: date) -> bool:
    with get_connection() as connection:
        try:
            connection.execute(
                "INSERT INTO patrimonio (equipamento, valor_aquisicao, data_aquisicao) VALUES (?, ?, ?)",
                (equipamento.strip(), valor, data_aquisicao.isoformat())
            )
            connection.commit()
            return True
        except sqlite3.IntegrityError:
            # Se o nome já existir, bloqueia duplicidade
            return False


def create_rental(
    equipamento: str,
    fornecedor: str,
    tipo_origem: str,
    obra: str,
    data_retirada: date,
    data_devolucao: date,
    custo_diario: float,
    custo_mensal: float,
    limite_dias: int,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO locacoes
                (equipamento, fornecedor, tipo_origem, obra, data_retirada, data_devolucao, custo_diario, custo_mensal, limite_dias)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                equipamento.strip(),
                fornecedor.strip(),
                tipo_origem,
                obra.strip(),
                data_retirada.isoformat(),
                data_devolucao.isoformat(),
                custo_diario,
                custo_mensal,
                limite_dias
            ),
        )
        connection.commit()


def close_rental(rental_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE locacoes
            SET status = 'Devolvida', data_baixa = ?
            WHERE id = ? AND status = 'Ativa'
            """,
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

    # Regra: Se tem custo mensal cadastrado, aplica a lógica do "virou mês"
    if mensal > 0:
        meses_cheios = days // 30
        dias_sobra = days % 30
        
        # Se os dias quebrados passarem do limite, cobra um mês cheio adicional
        if dias_sobra >= limite:
            meses_cheios += 1
            dias_sobra = 0
            
        return (meses_cheios * mensal) + (dias_sobra * diario)
    
    # Se não tem mensal, cobra estritamente por diária
    return days * diario


def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_date(value: object) -> str:
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


def render_sidebar() -> str:
    img = logo_path()
    if img:
        st.sidebar.image(str(img), use_container_width=True)
    st.sidebar.markdown("### CM Rental")
    st.sidebar.caption("Gestão Estratégica de Locações")
    st.sidebar.divider()
    menu = st.sidebar.radio(
        "Navegação",
        ["Nova Locação", "Equipamentos Alugados", "Dashboard", "Patrimônio (Ativos)"],
    )
    st.sidebar.divider()
    rentals = load_rentals()
    active_count = int((rentals["status"] == "Ativa").sum()) if not rentals.empty else 0
    st.sidebar.metric("Locações ativas", active_count)
    
    st.sidebar.divider()
    st.sidebar.markdown("👤 **Guilherme Macedo de Araújo Matias da Costa**")
    st.sidebar.caption("Operação CM Rental")
    
    return menu


def render_new_rental() -> None:
    st.title("Nova Locação")
    st.write("Registre a movimentação de um equipamento (próprio ou terceiro).")

    with st.form("new_rental_form", clear_on_submit=True):
        st.subheader("1. Dados do Equipamento")
        col_one, col_two = st.columns(2)
        with col_one:
            equipamento = st.text_input(
                "Identificação do Equipamento",
                placeholder="Ex.: Betoneira 01",
                help="Se for próprio, digite igualzinho cadastrou na aba de Patrimônio."
            )
            
            origem_sel = st.selectbox(
                "Origem do Equipamento / Fornecedor",
                FORNECEDORES_PADRAO,
            )
            
            fornecedor_custom = ""
            if origem_sel == "Outro (especificar)":
                fornecedor_custom = st.text_input("Digite o nome do fornecedor:")
                
            obra = st.selectbox("Obra de destino", OBRAS)
            
        with col_two:
            data_retirada = st.date_input(
                "Data de retirada / início",
                value=date.today(),
                format="DD/MM/YYYY",
            )
            data_devolucao = st.date_input(
                "Previsão de devolução",
                value=date.today() + timedelta(days=7),
                format="DD/MM/YYYY",
            )

        st.subheader("2. Regimes e Valores de Locação")
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            custo_diario = st.number_input(
                "Custo Diário (R$)",
                min_value=0.0, step=5.0, format="%.2f"
            )
        with col_c2:
            custo_mensal = st.number_input(
                "Custo Mensal (R$)",
                min_value=0.0, step=50.0, format="%.2f",
                help="Deixe R$ 0,00 se for cobrar apenas por diária pura."
            )
        with col_c3:
            limite_dias = st.number_input(
                "Dias p/ virar mês cheio",
                min_value=1, max_value=30, value=15,
                help="Ex: Se passar de 15 dias quebrados, cobra o valor do mês cheio."
            )

        submitted = st.form_submit_button(
            "Registrar Movimentação",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if origem_sel == "Outro (especificar)":
            fornecedor_final = fornecedor_custom.strip() if fornecedor_custom.strip() else "Outro"
            tipo_origem = "Terceiros"
        elif origem_sel == "Equipamento CM (Próprio)":
            fornecedor_final = "CM (Próprio)"
            tipo_origem = "Próprio (CM)"
        else:
            fornecedor_final = origem_sel
            tipo_origem = "Terceiros"

        if not equipamento.strip():
            st.error("Informe o nome/identificação do equipamento.")
        elif data_devolucao < data_retirada:
            st.error("A data de devolução deve ser igual ou posterior à retirada.")
        else:
            create_rental(
                equipamento=equipamento,
                fornecedor=fornecedor_final,
                tipo_origem=tipo_origem,
                obra=obra,
                data_retirada=data_retirada,
                data_devolucao=data_devolucao,
                custo_diario=custo_diario,
                custo_mensal=custo_mensal,
                limite_dias=int(limite_dias)
            )
            st.success(f"Equipamento '{equipamento}' registrado com sucesso!")
            st.rerun()


def render_active_rentals() -> None:
    st.title("Equipamentos em Uso / Alugados")
    st.write("Acompanhe prazos de devolução, origem e locações ativas por obra.")

    rentals = load_rentals()
    active = rentals[rentals["status"] == "Ativa"].copy()
    if active.empty:
        st.info("Não há equipamentos ativos no momento.")
        return

    overdue_count = sum(
        as_date(row["data_devolucao"]) < date.today()
        for _, row in active.iterrows()
    )
    
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Total em Uso", len(active))
    metric_two.metric("Próprios (CM)", int((active["tipo_origem"] == "Próprio (CM)").sum()))
    metric_three.metric("Terceirizados", int((active["tipo_origem"] == "Terceiros").sum()))
    metric_four.metric("Em atraso", overdue_count)

    # Aplica o calculo misto de custo em tempo real para ativos
    active["Custo Acumulado (R$)"] = active.apply(total_cost, axis=1).map(format_currency)

    table = active[
        [
            "id",
            "equipamento",
            "tipo_origem",
            "fornecedor",
            "obra",
            "data_retirada",
            "data_devolucao",
            "Custo Acumulado (R$)",
        ]
    ].copy()
    table.columns = [
        "ID", "Equipamento", "Origem", "Fornecedor", "Obra", "Retirada", "Devolução", "Custo Acumulado"
    ]
    table["Retirada"] = table["Retirada"].map(format_date)
    table["Devolução"] = table["Devolução"].map(format_date)
    table["Prazo"] = active.apply(deadline_label, axis=1).values
    
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.subheader("Dar baixa em devolução")
    rental_options = {
        f'#{row["id"]} · {row["equipamento"]} ({row["fornecedor"]}) · {row["obra"]}': int(row["id"])
        for _, row in active.iterrows()
    }
    selected_label = st.selectbox(
        "Selecione o equipamento devolvido / desmobilizado",
        list(rental_options.keys()),
    )
    if st.button("Dar Baixa", type="primary"):
        close_rental(rental_options[selected_label])
        st.success("Equipamento desmobilizado/devolvido com sucesso!")
        st.rerun()


def render_dashboard() -> None:
    st.title("Dashboard de Custos e Frentes")
    st.write("Análise de custos de locação por obra e por fornecedor.")

    rentals = load_rentals()
    if rentals.empty:
        st.info("Cadastre a primeira locação para habilitar os relatórios do dashboard.")
        return

    rentals["dias_cobrados"] = rentals.apply(rental_days, axis=1)
    rentals["custo_total"] = rentals.apply(total_cost, axis=1)

    total_cost_value = float(rentals["custo_total"].sum())

    col1, col2 = st.columns(2)
    col1.metric("Custo Total Acumulado (Próprios + Terceiros)", format_currency(total_cost_value))

    st.divider()
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.subheader("Custo Total por Obra")
        by_work = (
            rentals.groupby("obra")["custo_total"]
            .sum()
            .sort_values(ascending=False)
            .to_frame("Custo Total")
        )
        st.bar_chart(by_work, color="#F35A24")

    with col_g2:
        st.subheader("Custo por Fornecedor / Origem")
        by_supplier = (
            rentals.groupby("fornecedor")["custo_total"]
            .sum()
            .sort_values(ascending=False)
            .to_frame("Custo Total")
        )
        st.bar_chart(by_supplier, color="#1F77B4")

    st.subheader("Detalhamento Geral")
    resumo_df = rentals.groupby(["obra", "fornecedor", "tipo_origem"])["custo_total"].sum().reset_index()
    resumo_df.columns = ["Obra", "Fornecedor", "Tipo", "Custo Total"]
    resumo_df["Custo Total"] = resumo_df["Custo Total"].map(format_currency)
    st.dataframe(resumo_df, hide_index=True, use_container_width=True)


def render_patrimonio() -> None:
    st.title("Patrimônio (Equipamentos CM)")
    st.write("Cadastre os equipamentos próprios da empresa para calcular o seu valor de patrimônio e o retorno de investimento (ROI) gerado pelas locações.")

    with st.form("new_asset_form", clear_on_submit=True):
        st.subheader("Cadastrar Novo Ativo")
        c1, c2, c3 = st.columns(3)
        with c1:
            nome_eq = st.text_input("Identificação do Equipamento", placeholder="Ex: Betoneira 400L - 01")
        with c2:
            valor_eq = st.number_input("Valor de Aquisição (R$)", min_value=0.0, step=100.0)
        with c3:
            data_aq = st.date_input("Data de Aquisição", format="DD/MM/YYYY")
            
        sub = st.form_submit_button("Cadastrar ao Patrimônio", type="primary")
        if sub:
            if nome_eq.strip():
                if create_patrimonio(nome_eq, valor_eq, data_aq):
                    st.success("Equipamento adicionado ao patrimônio!")
                    st.rerun()
                else:
                    st.error("Já existe um equipamento com essa identificação exata.")
            else:
                st.error("Preencha a identificação do equipamento.")

    st.divider()
    
    patrimonio_df = load_patrimonio()
    if patrimonio_df.empty:
        st.info("Nenhum equipamento próprio cadastrado no patrimônio ainda.")
        return

    # Painel de Patrimônio
    total_patrimonio = patrimonio_df["valor_aquisicao"].sum()
    st.metric("💰 Valor Total do Patrimônio (Ativos)", format_currency(total_patrimonio))

    # Calculando os ganhos/economia de cada equipamento
    locacoes_df = load_rentals()
    locacoes_df["custo_total"] = locacoes_df.apply(total_cost, axis=1)
    
    # Filtra só os próprios e soma pelo nome exato do equipamento
    ganhos = locacoes_df[locacoes_df["tipo_origem"] == "Próprio (CM)"].groupby("equipamento")["custo_total"].sum().reset_index()
    ganhos.rename(columns={"custo_total": "retorno_gerado"}, inplace=True)

    # Junta a tabela de patrimônio com os ganhos
    merged = pd.merge(patrimonio_df, ganhos, on="equipamento", how="left")
    merged["retorno_gerado"] = merged["retorno_gerado"].fillna(0)
    
    # Impede divisão por zero no ROI
    merged["roi_perc"] = merged.apply(
        lambda row: (row["retorno_gerado"] / row["valor_aquisicao"] * 100) if row["valor_aquisicao"] > 0 else 0, 
        axis=1
    )

    st.subheader("Relação de Ativos e Retorno")
    display_df = merged[["equipamento", "data_aquisicao", "valor_aquisicao", "retorno_gerado", "roi_perc"]].copy()
    display_df.columns = ["Equipamento", "Data Aquisição", "Valor Investido", "Retorno (Locações)", "ROI (%)"]
    
    display_df["Data Aquisição"] = display_df["Data Aquisição"].map(format_date)
    display_df["Valor Investido"] = display_df["Valor Investido"].map(format_currency)
    display_df["Retorno (Locações)"] = display_df["Retorno (Locações)"].map(format_currency)
    display_df["ROI (%)"] = display_df["ROI (%)"].apply(lambda x: f"{x:,.2f}%".replace('.',','))

    st.dataframe(display_df, hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(
        page_title="CM Rental | Controle de locações",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_db()
    menu = render_sidebar()

    if menu == "Nova Locação":
        render_new_rental()
    elif menu == "Equipamentos Alugados":
        render_active_rentals()
    elif menu == "Patrimônio (Ativos)":
        render_patrimonio()
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
