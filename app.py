import streamlit as st
import pandas as pd
import json
import os
import uuid
import re
from fpdf import FPDF
from datetime import datetime
from groq import Groq, RateLimitError
from supabase import create_client, Client
from dotenv import load_dotenv

# 1. INFRAESTRUCTURA Y CONFIGURACIÓN
load_dotenv()
try:
    supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    client_ia = Groq(api_key=os.environ.get("GROQ_API_KEY"))
except Exception as e:
    st.error(f"Falla de conexión con infraestructura: {e}")

MODELO_CHAT = "llama-3.1-8b-instant"

st.set_page_config(page_title="Massive Enterprise Hub", layout="wide", page_icon="🇪🇨")

# --- 2. CAPA DE SERVICIOS (PDF Y PERSISTENCIA) ---

class MassiveServices:
    @staticmethod
    def generar_proforma_pdf(user_data, total):
        """Genera el documento PDF legal para el cliente."""
        pdf = FPDF()
        pdf.add_page()
        # Estética de marca
        pdf.set_fill_color(15, 35, 75)
        pdf.rect(0, 0, 210, 45, 'F')
        pdf.set_font("Arial", "B", 22)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 25, "MASSIVE SOLUTIONS - PROFORMA OFICIAL", ln=True, align='C')
        
        pdf.set_text_color(0, 0, 0)
        pdf.ln(25)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "DETALLES DEL CLIENTE (QUITO - ECUADOR)", ln=True)
        pdf.set_font("Arial", "", 11)
        pdf.cell(0, 7, f"Nombre: {user_data.get('nombre')}", ln=True)
        pdf.cell(0, 7, f"Cédula/RUC: {user_data.get('cedula')}", ln=True)
        pdf.cell(0, 7, f"Teléfono: {user_data.get('telefono')}", ln=True)
        
        pdf.ln(10)
        subtotal = total / 1.12
        iva = total - subtotal
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "B", 13)
        pdf.cell(0, 12, f" VALOR TOTAL A PAGAR: ${total:,.2f} USD", ln=True, fill=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 6, f"Subtotal: ${subtotal:,.2f} | IVA 12%: ${iva:,.2f}", ln=True)
        
        pdf.ln(20)
        pdf.set_font("Arial", "I", 9)
        pdf.multi_cell(0, 5, "Nota: Esta proforma es un documento informativo para retiro en local físico. No es una factura electrónica. Válido por 24 horas.")
        return pdf.output()

def filtrar_contexto(prompt, catalogo):
    """Busca productos en el catálogo basándose en el lenguaje del usuario."""
    p_low = prompt.lower()
    if any(x in p_low for x in ["laptop", "portatil", "notebook"]):
        res = [p for p in catalogo if p.get('subcategoria', '').lower() == 'laptops']
    elif any(x in p_low for x in ["pc", "desktop", "all in one"]):
        res = [p for p in catalogo if p.get('subcategoria', '').lower() in ['desktop', 'mini pc', 'all in one']]
    else:
        tags = re.findall(r'\b\w{3,}\b', p_low)
        res = [p for p in catalogo if any(t in p['nombre'].lower() for t in tags)]
    return res[:10] if res else catalogo[:6]

# --- 3. MÓDULO DE ATENCIÓN AL CLIENTE ---

def modulo_atencion(catalogo):
    st.title("🤖 Asesor Massive Intelligence")

    # Inicialización de Estados
    if "session_id" not in st.session_state: st.session_state.session_id = uuid.uuid4()
    if "chat_active" not in st.session_state: st.session_state.chat_active = True
    if "messages" not in st.session_state: 
        st.session_state.messages = [{"role": "assistant", "content": "¡Qué gusto saludarle, jefe! Bienvenido a Massive. ¿Qué equipo le interesa ver hoy o necesita soporte técnico?"}]
    if "user_data" not in st.session_state: st.session_state.user_data = None
    if "total_final" not in st.session_state: st.session_state.total_final = 0
    if "esperando_datos" not in st.session_state: st.session_state.esperando_datos = False

    # Pantalla de descarga de PDF al finalizar
    if not st.session_state.chat_active:
        st.success("✅ Proforma generada satisfactoriamente.")
        pdf_bytes = MassiveServices.generar_proforma_pdf(st.session_state.user_data, st.session_state.total_final)
        st.download_button("📩 Descargar Proforma PDF", data=pdf_bytes, file_name=f"cotizacion_{st.session_state.user_data['cedula']}.pdf", mime="application/pdf")
        if st.button("Abrir nueva sesión"):
            st.session_state.clear()
            st.rerun()
        return

    # Renderizado del historial de chat
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("Escriba aquí su mensaje..."):
        
        # INTERCEPCIÓN DINÁMICA DE DATOS
        if st.session_state.esperando_datos:
            pts = [x.strip() for x in prompt.split(",")]
            if len(pts) >= 3:
                st.session_state.user_data = {"nombre": pts[0], "cedula": pts[1], "telefono": pts[2]}
                supabase.table("clientes").upsert(st.session_state.user_data).execute()
                st.session_state.esperando_datos = False
                prompt = f"Mis datos son {pts[0]}. Procede a generar el TICKET DE COTIZACIÓN ahora mismo."
            else:
                st.error("Por favor, jefe, envíe: Nombre, Cédula, Teléfono (separados por comas).")
                return

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        # LÓGICA DE RESPUESTA DE LA IA
        with st.chat_message("assistant"):
            items = filtrar_contexto(prompt, catalogo)
            ctx = "\n".join([f"- {p['nombre']} (${p['precio']} USD): {p['especificaciones']}" for p in items])
            
            sys_msg = f"""Eres el asesor experto de Massive. Tono ecuatoriano cordial y eficiente.
            PRODUCTOS DISPONIBLES: {ctx}
            
            FLUJO DE TRABAJO:
            1. Si el usuario pide ver opciones, muéstralas con precios y especificaciones.
            2. NO pidas datos personales de entrada. Solo pídeles cuando digan que quieren cotizar o comprar.
            3. SI EL USUARIO PIDE COTIZAR/COMPRAR: 
               - Si NO tienes sus datos, dile: '¡De una jefe! Para generarle la proforma PDF, por favor páseme su Nombre, Cédula y Teléfono (separados por comas)'.
            4. Cuando ya tengas los datos, genera el 'TICKET DE COTIZACIÓN' con desglose de IVA 12% y el TOTAL final.
            """

            try:
                r = client_ia.chat.completions.create(messages=[{"role": "system", "content": sys_msg}] + st.session_state.messages, model=MODELO_CHAT, temperature=0.3)
                resp = r.choices[0].message.content
                
                # Gestión de estados internos basada en la respuesta de la IA
                if any(x in resp.lower() for x in ["páseme su nombre", "proporcione sus datos", "necesito su cédula"]):
                    st.session_state.esperando_datos = True

                if "TICKET DE COTIZACIÓN" in resp:
                    match = re.search(r'TOTAL: \$([\d,.]+)', resp)
                    if match:
                        st.session_state.total_final = float(match.group(1).replace(",", ""))
                        if st.session_state.user_data:
                            supabase.table("cotizaciones").insert({
                                "cliente_id": st.session_state.user_data['cedula'],
                                "monto_total": st.session_state.total_final,
                                "session_id": str(st.session_state.session_id)
                            }).execute()
                            st.session_state.chat_active = False

                st.markdown(resp)
                st.session_state.messages.append({"role": "assistant", "content": resp})
                # Persistencia del log de charla
                supabase.table("conversaciones").insert({"session_id": str(st.session_state.session_id), "mensaje_usuario": prompt, "respuesta_ia": resp}).execute()
            except Exception as e:
                st.error(f"Error de comunicación: {e}")

# --- 4. DASHBOARD ADMINISTRATIVO (BI EXECUTIVE) ---

def modulo_admin():
    st.title("📊 Massive Executive Dashboard")
    try:
        q = pd.DataFrame(supabase.table("cotizaciones").select("*").execute().data)
        l = pd.DataFrame(supabase.table("clientes").select("*").execute().data)
        c = pd.DataFrame(supabase.table("conversaciones").select("*").execute().data)
    except: q, l, c = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # MÉTRICAS DE ALTO IMPACTO
    k1, k2, k3, k4 = st.columns(4)
    if not q.empty:
        total_revenue = q['monto_total'].sum()
        k1.metric("Revenue Proyectado", f"${total_revenue:,.2f} USD")
        k2.metric("Ticket Promedio", f"${total_revenue/len(q):,.2f}")
    if not l.empty:
        k3.metric("Total Leads (Clientes)", len(l))
    if not c.empty:
        k4.metric("Interacciones Totales", len(c))

    st.divider()

    col_izq, col_der = st.columns([1, 2])
    with col_izq:
        st.subheader("👥 Últimos Leads Captados")
        if not l.empty:
            st.dataframe(l.tail(10)[['nombre', 'cedula', 'telefono']], use_container_width=True)
    
    with col_der:
        st.subheader("🕵️ Auditoría de Sesiones")
        if not c.empty:
            sid = st.selectbox("Seleccione Sesión para Revisar:", c['session_id'].unique())
            sesion_data = c[c['session_id'] == sid]
            for _, r in sesion_data.iterrows():
                st.info(f"👤 {r['mensaje_usuario']}")
                st.caption(f"🤖 {r['respuesta_ia']}")

# --- 5. CONTROLADOR PRINCIPAL ---

def main():
    try:
        catalogo = supabase.table("productos").select("*").execute().data
    except:
        catalogo = []
        st.warning("No se pudo cargar el catálogo de Supabase.")

    with st.sidebar:
        st.image("logo_massive.jpg", width=200)
        st.title("Massive v9.5")
        mode = st.radio("Sección:", ["Atención Cliente", "Admin Dashboard"])
        st.divider()
        st.caption("Architect: Byron Caldas")

    if mode == "Atención Cliente":
        modulo_atencion(catalogo)
    else:
        modulo_admin()

if __name__ == "__main__":
    main()
