# Cần cài đặt:
# pip install streamlit pandas numpy_financial google-genai python-docx

import streamlit as st
import pandas as pd
import numpy as np
import numpy_financial as npf # Thư viện tính toán tài chính như NPV, IRR
from google import genai
from google.genai.errors import APIError
from docx import Document
import io
import json

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="App Đánh giá Dự án Đầu tư (AI)",
    layout="wide"
)

st.title("Ứng dụng Đánh giá Dự án Đầu tư 📈")
st.markdown("Sử dụng Gemini AI để trích xuất dữ liệu từ file Word (.docx), xây dựng dòng tiền và tính toán hiệu quả dự án.")

# --- Thiết lập API Key ---
# Đảm bảo bạn đã cấu hình 'GEMINI_API_KEY' trong Streamlit Secrets
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    API_KEY = None
    st.error("Lỗi: Không tìm thấy Khóa API 'GEMINI_API_KEY'. Vui lòng cấu hình trong Streamlit Secrets.")

# --- 1. Hàm Trích xuất Dữ liệu từ Word bằng AI ---

def extract_text_from_docx(file):
    """Đọc và trích xuất toàn bộ văn bản từ file Word đã upload."""
    try:
        # docx.Document() cần một đối tượng file-like
        document = Document(io.BytesIO(file.read()))
        text = "\n".join([paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()])
        return text
    except Exception as e:
        st.error(f"Lỗi khi đọc file DOCX: {e}")
        return None

def ai_extract_financial_parameters(document_text, api_key):
    """
    Sử dụng Gemini AI với JSON Schema để trích xuất các thông số tài chính.
    """
    if not api_key:
        return None, "Lỗi API Key: Vui lòng cung cấp Khóa API Gemini."

    client = genai.Client(api_key=api_key)
    model_name = 'gemini-2.5-flash'
    
    # Định nghĩa cấu trúc JSON cần trích xuất (Task 1)
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "Vốn_Đầu_Tư": {"type": "NUMBER", "description": "Tổng vốn đầu tư ban đầu của dự án (luôn là số dương, đơn vị triệu/tỷ đồng)."},
            "Dòng_Đời_Dự_Án": {"type": "INTEGER", "description": "Số năm hoạt động của dự án (tối đa 20 năm)."},
            "Doanh_Thu_Hàng_Năm": {"type": "NUMBER", "description": "Doanh thu ước tính hàng năm (Giả định cố định, đơn vị triệu/tỷ đồng)."},
            "Chi_Phí_Hàng_Năm": {"type": "NUMBER", "description": "Tổng chi phí hoạt động ước tính hàng năm (chưa bao gồm Khấu hao và Lãi vay, đơn vị triệu/tỷ đồng)."},
            "WACC": {"type": "NUMBER", "description": "Tỷ lệ chi phí sử dụng vốn (WACC) dưới dạng thập phân (ví dụ: 0.10 cho 10%)."},
            "Thuế_Suất": {"type": "NUMBER", "description": "Thuế suất thu nhập doanh nghiệp dưới dạng thập phân (ví dụ: 0.20 cho 20%)."}
        },
        "required": ["Vốn_Đầu_Tư", "Dòng_Đời_Dự_Án", "Doanh_Thu_Hàng_Năm", "Chi_Phí_Hàng_Năm", "WACC", "Thuế_Suất"]
    }
    
    system_prompt = (
        "Bạn là một chuyên gia tài chính. Hãy đọc nội dung văn bản kinh doanh bên dưới và trích xuất CHÍNH XÁC "
        "các thông số tài chính vào cấu trúc JSON được cung cấp. Tất cả các giá trị (trừ vốn và tuổi thọ) phải được "
        "chuyển đổi thành SỐ NGUYÊN/SỐ THỰC, KHÔNG để dấu phẩy, KHÔNG có đơn vị (ví dụ: '1000' chứ không phải '1,000 tỷ'). "
        "Chi phí được hiểu là chi phí hoạt động không bao gồm khấu hao và lãi vay."
    )

    prompt = f"Trích xuất các thông số tài chính từ báo cáo này: \n\n{document_text}"

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "response_schema": response_schema
            }
        )
        # Parse JSON output
        extracted_data = json.loads(response.text)
        return extracted_data, "Trích xuất dữ liệu thành công."

    except APIError as e:
        return None, f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API hoặc giới hạn sử dụng. Chi tiết lỗi: {e}"
    except Exception as e:
        # Bao gồm lỗi parsing JSON
        st.error(f"Phản hồi của AI không hợp lệ hoặc lỗi xử lý JSON: {response.text}")
        return None, f"Đã xảy ra lỗi không xác định: {e}"

# --- 2. Hàm Xây dựng Bảng Dòng Tiền & 3. Tính toán Chỉ số ---

# Khấu hao đường thẳng (Giả định TSLN = 0)
def calculate_depreciation(investment, lifespan):
    return investment / lifespan

def build_cash_flow_and_calculate_metrics(params):
    """
    Xây dựng bảng dòng tiền và tính toán các chỉ số hiệu quả dự án. (Task 2 & 3)
    """
    # Lấy thông số
    I0 = params['Vốn_Đầu_Tư']
    N = params['Dòng_Đời_Dự_Án']
    R = params['Doanh_Thu_Hàng_Năm']
    C = params['Chi_Phí_Hàng_Năm']
    WACC = params['WACC']
    T = params['Thuế_Suất']
    
    D = calculate_depreciation(I0, N) # Khấu hao hàng năm

    # Xây dựng Dòng Tiền
    years = np.arange(0, N + 1)
    
    # Khởi tạo các dòng tiền bằng 0
    df = pd.DataFrame(index=years)
    df.index.name = 'Năm'
    
    # 1. Dòng Doanh thu, Chi phí, Khấu hao
    df['Doanh thu (R)'] = R
    df['Chi phí (C)'] = C
    df['Khấu hao (D)'] = D
    
    # 2. Lợi nhuận trước thuế và lãi vay (EBT)
    df['Lợi nhuận trước thuế (EBT)'] = df['Doanh thu (R)'] - df['Chi phí (C)'] - df['Khấu hao (D)']
    
    # 3. Thuế (Tax)
    df['Thuế (Tax)'] = np.where(df['Lợi nhuận trước thuế (EBT)'] > 0, df['Lợi nhuận trước thuế (EBT)'] * T, 0)
    
    # 4. Dòng tiền ròng từ hoạt động (OCF)
    # OCF = EBT - Tax + D
    df['OCF'] = df['Lợi nhuận trước thuế (EBT)'] - df['Thuế (Tax)'] + df['Khấu hao (D)']
    
    # 5. Dòng tiền ròng của dự án (NCF)
    df['NCF'] = df['OCF']
    df.loc[0, 'NCF'] = -I0 # Vốn đầu tư ban đầu (Outflow)

    # --- Tính toán Chỉ số Hiệu quả (Task 3) ---
    cash_flows = df['NCF'].tolist()
    
    # 1. NPV
    npv = npf.npv(WACC, cash_flows)
    
    # 2. IRR
    try:
        irr = npf.irr(cash_flows)
    except:
        irr = np.nan # NaN nếu không tìm được IRR

    # 3. Payback Period (PP) - Thời gian hoàn vốn
    cumulative_cf = np.cumsum(cash_flows)
    pp_year = np.argmax(cumulative_cf >= 0)
    pp_fraction = (cumulative_cf[pp_year-1] * -1) / cash_flows[pp_year]
    pp = pp_year - 1 + pp_fraction if pp_year > 0 else 0

    # 4. Discounted Payback Period (DPP) - Thời gian hoàn vốn có chiết khấu
    discounted_cf = [cf / ((1 + WACC) ** year) for year, cf in enumerate(cash_flows)]
    cumulative_dcf = np.cumsum(discounted_cf)
    dpp_year = np.argmax(cumulative_dcf >= 0)
    dpp_fraction = (cumulative_dcf[dpp_year-1] * -1) / discounted_cf[dpp_year]
    dpp = dpp_year - 1 + dpp_fraction if dpp_year > 0 else 0

    metrics = {
        'NPV': npv,
        'IRR': irr,
        'PP': pp,
        'DPP': dpp,
        'Dòng Đời Dự Án': N
    }
    
    return df, metrics

# --- 4. Hàm Phân tích AI các Chỉ số Hiệu quả ---

def ai_analyze_metrics(metrics, api_key):
    """Gửi các chỉ số NPV, IRR, PP, DPP đến AI để phân tích."""
    if not api_key:
        return "Lỗi API Key: Vui lòng cung cấp Khóa API Gemini."

    client = genai.Client(api_key=api_key)
    model_name = 'gemini-2.5-flash'
    
    metrics_str = "\n".join([f"- {k}: {v:.2f}" for k, v in metrics.items() if k not in ['Dòng Đời Dự Án']])
    
    system_prompt = (
        "Bạn là một nhà tư vấn tài chính cấp cao chuyên về đánh giá dự án đầu tư. "
        "Nhiệm vụ của bạn là phân tích các chỉ số hiệu quả dự án (NPV, IRR, PP, DPP) và "
        "đưa ra nhận định rõ ràng về tính khả thi, độ hấp dẫn, và rủi ro của dự án. "
        "Phản hồi phải: 1) Nhận định NPV và IRR (dự án có nên được chấp nhận không?), "
        "2) So sánh IRR với WACC, 3) Đánh giá thời gian hoàn vốn (PP/DPP) so với tuổi thọ dự án. "
        "Trình bày kết quả dưới 3 đoạn văn ngắn gọn bằng tiếng Việt."
    )

    prompt = f"""
    Hãy phân tích chi tiết các chỉ số hiệu quả sau của dự án:
    
    - Chi phí sử dụng vốn (WACC): {metrics['WACC']:.2%}
    - Dòng đời dự án (N): {metrics['Dòng Đời Dự Án']} năm
    {metrics_str}
    """

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={"system_instruction": system_prompt}
        )
        return response.text
    except APIError as e:
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API. Chi tiết lỗi: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định: {e}"

# --- Giao diện Streamlit Chính ---

# Khởi tạo State
if 'extracted_params' not in st.session_state:
    st.session_state.extracted_params = None
if 'df_cash_flow' not in st.session_state:
    st.session_state.df_cash_flow = None
if 'metrics' not in st.session_state:
    st.session_state.metrics = None
if 'ai_analysis' not in st.session_state:
    st.session_state.ai_analysis = None


# --- 1. Upload File Word ---
st.subheader("1. Tải lên File Word (.docx) chứa Phương án Kinh doanh")
uploaded_file = st.file_uploader(
    "Vui lòng tải file Word (.docx). File nên chứa các thông tin về vốn đầu tư, doanh thu, chi phí, tuổi thọ, WACC, và thuế.",
    type=['docx']
)

if uploaded_file:
    # --- Nút Lọc Dữ liệu ---
    if st.button("Trích xuất Dữ liệu Tài chính bằng AI (Bước 1)", type="primary"):
        with st.spinner('Đang đọc file và gửi nội dung cho AI trích xuất...'):
            document_text = extract_text_from_docx(uploaded_file)

            if document_text:
                params, message = ai_extract_financial_parameters(document_text, API_KEY)
                
                if params:
                    st.session_state.extracted_params = params
                    # Sau khi trích xuất thành công, tính toán luôn Dòng tiền và Chỉ số
                    df_cf, metrics = build_cash_flow_and_calculate_metrics(params)
                    st.session_state.df_cash_flow = df_cf
                    st.session_state.metrics = metrics
                    st.success(f"{message} Đã sẵn sàng để xem kết quả.")
                else:
                    st.session_state.extracted_params = None
                    st.error(f"Trích xuất thất bại: {message}")
            else:
                st.session_state.extracted_params = None

# --- Hiển thị Kết quả nếu đã trích xuất ---
if st.session_state.extracted_params:
    params = st.session_state.extracted_params
    
    st.markdown("---")
    st.subheader("Trích xuất Dữ liệu Tài chính Thành công (Task 1)")
    
    col_params_1, col_params_2, col_params_3 = st.columns(3)
    
    with col_params_1:
        st.metric("Vốn Đầu tư (I₀)", f"{params['Vốn_Đầu_Tư']:,.0f}")
        st.metric("Doanh thu Hàng năm", f"{params['Doanh_Thu_Hàng_Năm']:,.0f}")
    with col_params_2:
        st.metric("Dòng đời Dự án (N)", f"{params['Dòng_Đời_Dự_Án']} năm")
        st.metric("Chi phí Hàng năm", f"{params['Chi_Phí_Hàng_Năm']:,.0f}")
    with col_params_3:
        st.metric("WACC", f"{params['WACC']:.2%}")
        st.metric("Thuế suất (T)", f"{params['Thuế_Suất']:.0%}")
        
    st.markdown("---")
    
    # --- Xây dựng Bảng Dòng Tiền (Task 2) ---
    st.subheader("2. Bảng Dòng tiền Ròng (NCF) của Dự án (Task 2)")
    df_cf = st.session_state.df_cash_flow
    
    # Định dạng hiển thị
    st.dataframe(df_cf.style.format({
        col: '{:,.0f}' for col in df_cf.columns
    }), use_container_width=True)
    
    st.info("NCF: Dòng tiền ròng của dự án (Net Cash Flow).")
    st.markdown("---")
    
    # --- Tính toán Chỉ số Đánh giá (Task 3) ---
    st.subheader("3. Các Chỉ số Đánh giá Hiệu quả Dự án (Task 3)")
    metrics = st.session_state.metrics
    
    col_metrics_1, col_metrics_2, col_metrics_3, col_metrics_4 = st.columns(4)
    
    with col_metrics_1:
        st.metric("Giá trị Hiện tại Ròng (NPV)", f"{metrics['NPV']:,.0f}")
    with col_metrics_2:
        # Nếu IRR là NaN, hiển thị 'N/A'
        irr_value = f"{metrics['IRR']:.2%}" if not np.isnan(metrics['IRR']) else "N/A"
        st.metric("Tỷ suất Hoàn vốn Nội bộ (IRR)", irr_value)
    with col_metrics_3:
        st.metric("Thời gian Hoàn vốn (PP)", f"{metrics['PP']:.2f} năm")
    with col_metrics_4:
        st.metric("Thời gian Hoàn vốn có Chiết khấu (DPP)", f"{metrics['DPP']:.2f} năm")

    st.markdown("---")

    # --- Yêu cầu AI Phân tích (Task 4) ---
    st.subheader("4. Phân tích Các Chỉ số Hiệu quả Dự án (AI) (Task 4)")
    
    if st.button("Yêu cầu AI Phân tích Hiệu quả Dự án", key="ai_analysis_btn"):
        with st.spinner('Đang gửi dữ liệu và chờ Gemini phân tích...'):
            ai_result = ai_analyze_metrics(metrics, API_KEY)
            st.session_state.ai_analysis = ai_result
            
    if st.session_state.ai_analysis:
        st.markdown("**Kết quả Phân tích từ Gemini AI:**")
        st.info(st.session_state.ai_analysis)

# Footer
st.markdown("---")
st.caption("Lưu ý: Ứng dụng giả định doanh thu/chi phí không đổi và khấu hao đường thẳng. WACC và Thuế suất là các tỷ lệ cố định.")
