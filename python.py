# app.py

import streamlit as st
import pandas as pd
import numpy as np
from google import genai
from google.genai.errors import APIError
from docx import Document
import json # Thư viện cần thiết để xử lý đầu ra JSON của AI

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="App Đánh giá Phương án Kinh doanh",
    layout="wide"
)

st.title("Ứng dụng Đánh giá Hiệu quả Dự án Đầu tư 💰")

# --- Hàm đọc nội dung từ file Word (.docx) ---
def read_docx(file):
    """Đọc toàn bộ nội dung văn bản từ file .docx đã tải lên."""
    try:
        document = Document(file)
        full_text = []
        for para in document.paragraphs:
            full_text.append(para.text)
        return '\n'.join(full_text)
    except Exception as e:
        st.error(f"Lỗi khi đọc file Word: {e}")
        return None

# --- Hàm Gọi API Gemini để Lọc Dữ liệu (Nhiệm vụ 1) ---
@st.cache_data(show_spinner="Đang dùng AI để lọc các tham số dự án...")
def extract_project_data(project_text, api_key):
    """
    Sử dụng Gemini để trích xuất các tham số dự án từ văn bản thô.
    Yêu cầu AI trả về định dạng JSON để dễ dàng xử lý.
    """
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash' 

        # Danh sách các tham số cần trích xuất
        params_list = [
            "Vốn đầu tư ban đầu (Initial Investment - Cần là một số dương)",
            "Dòng đời dự án (Project Life - Số năm)",
            "Doanh thu thuần hàng năm (Annual Revenue - Số tiền ước tính cho mỗi năm)",
            "Chi phí hoạt động hàng năm (Annual Operating Cost - Số tiền ước tính cho mỗi năm, KHÔNG bao gồm Chi phí khấu hao)",
            "WACC (Weighted Average Cost of Capital - Tỷ lệ chiết khấu, Dạng thập phân, ví dụ: 0.10 cho 10%)",
            "Thuế suất doanh nghiệp (Tax Rate - Dạng thập phân, ví dụ: 0.20 cho 20%)",
            "Tỷ lệ Khấu hao hàng năm (Annual Depreciation - Dạng thập phân của vốn đầu tư, giả định khấu hao đường thẳng, ví dụ: 1/Dòng đời dự án)"
        ]

        # Khung JSON mong muốn
        json_schema = {
            "Vốn đầu tư": "float",
            "Dòng đời dự án": "int",
            "Doanh thu": "float",
            "Chi phí": "float",
            "WACC": "float",
            "Thuế": "float",
            "Khấu hao": "float" 
        }

        prompt = f"""
        Bạn là một mô hình AI chuyên trích xuất dữ liệu tài chính từ văn bản phi cấu trúc. 
        Hãy phân tích văn bản phương án kinh doanh sau và trích xuất các thông tin sau: {', '.join(params_list)}.
        
        Nếu không tìm thấy giá trị, hãy đặt là 0.0 hoặc 0 (tùy theo kiểu dữ liệu) nhưng luôn giữ nguyên cấu trúc JSON.
        
        YÊU CẦU: Chỉ trả về một đối tượng JSON DUY NHẤT theo cấu trúc sau (Đơn vị tiền tệ là VNĐ):
        {json.dumps(json_schema, indent=4)}
        
        Văn bản phương án kinh doanh:\n---START---\n{project_text}\n---END---
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        # Thử parse chuỗi JSON
        return json.loads(response.text.strip().replace('```json', '').replace('```', ''))

    except APIError as e:
        st.error(f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API hoặc giới hạn sử dụng. Chi tiết lỗi: {e}")
        return None
    except json.JSONDecodeError:
        st.warning("AI không trả về JSON hợp lệ. Vui lòng thử lại hoặc điều chỉnh file đầu vào.")
        st.code(response.text)
        return None
    except Exception as e:
        st.error(f"Đã xảy ra lỗi không xác định: {e}")
        return None

# --- Hàm Xây dựng Bảng Dòng Tiền (Nhiệm vụ 2) ---
def build_cash_flow_table(data):
    """Xây dựng Bảng Dòng tiền (CF) và tính các chỉ số."""
    
    # Gán các biến từ dữ liệu đã lọc (cần đảm bảo chúng là số)
    I_0 = data.get("Vốn đầu tư", 0.0)
    T = int(data.get("Dòng đời dự án", 0))
    R = data.get("Doanh thu", 0.0)
    C = data.get("Chi phí", 0.0) # Chi phí hoạt động, KHÔNG bao gồm khấu hao
    r = data.get("WACC", 0.0)
    tax_rate = data.get("Thuế", 0.0)
    dep_rate = data.get("Khấu hao", 0.0)
    
    # Kiểm tra điều kiện cần thiết
    if T <= 0 or r <= 0:
        st.error("Dữ liệu lọc không hợp lệ: Dòng đời dự án và WACC phải lớn hơn 0.")
        return None, None
        
    # Tính Khấu hao hàng năm (D = Vốn đầu tư * Tỷ lệ Khấu hao)
    D = I_0 * dep_rate 
    
    # Tạo các năm dự án: Năm 0 (Đầu tư) và Năm 1 đến T (Hoạt động)
    years = list(range(T + 1))
    
    # Khởi tạo DataFrame
    df = pd.DataFrame(index=years)
    
    # --- BẢNG DÒNG TIỀN DỰ KIẾN (Incremental Cash Flow) ---
    
    # 1. Thu nhập trước Thuế và Khấu hao (EBITDA)
    EBITDA = R - C
    
    # 2. Lãi trước Thuế và Lãi (EBIT = EBITDA - D)
    EBIT = EBITDA - D
    
    # 3. Thuế (Tax = EBIT * Thuế suất, nếu EBIT > 0)
    Tax = np.maximum(0, EBIT) * tax_rate
    
    # 4. Lợi nhuận ròng (NI = EBIT - Tax)
    NI = EBIT - Tax
    
    # 5. Dòng tiền thuần hàng năm (Annual Operating Cash Flow - OCF = NI + D)
    # Vì Khấu hao là chi phí không bằng tiền, nên phải cộng ngược lại
    OCF = NI + D
    
    # 6. Dòng tiền thuần của Dự án (Net Cash Flow - NCF)
    
    # Năm 0 (Đầu tư)
    df.loc[0, 'Diễn giải'] = 'Vốn Đầu tư Ban đầu'
    df.loc[0, 'Dòng tiền'] = -I_0
    df.loc[0, 'Chiết khấu'] = 1 / ((1 + r)**0) # = 1
    
    # Năm 1 đến T (Hoạt động)
    for t in range(1, T + 1):
        df.loc[t, 'Diễn giải'] = f'Dòng tiền Hoạt động Năm {t}'
        df.loc[t, 'Dòng tiền'] = OCF # Giả định dòng tiền đều hàng năm
        df.loc[t, 'Chiết khấu'] = 1 / ((1 + r)**t)
    
    # Tính Dòng tiền Chiết khấu
    df['Dòng tiền Chiết khấu'] = df['Dòng tiền'] * df['Chiết khấu']
    
    # Tính Dòng tiền tích lũy (Cộng dồn)
    df['Dòng tiền Tích lũy'] = df['Dòng tiền'].cumsum()
    df['Dòng tiền Chiết khấu Tích lũy'] = df['Dòng tiền Chiết khấu'].cumsum()
    
    return df, r

# --- Hàm Tính toán các Chỉ số Đánh giá (Nhiệm vụ 3) ---
def calculate_metrics(df, r):
    """Tính NPV, IRR, PP, DPP."""
    
    cash_flows = df['Dòng tiền'].tolist()
    discounted_cash_flows = df['Dòng tiền Chiết khấu'].tolist()

    # 1. NPV (Net Present Value)
    NPV = sum(discounted_cash_flows)
    
    # 2. IRR (Internal Rate of Return)
    try:
        # numpy.irr yêu cầu list dòng tiền
        IRR = np.irr(cash_flows) 
    except:
        IRR = np.nan
        
    # 3. PP (Payback Period - Thời gian hoàn vốn)
    # Lấy Dòng tiền tích lũy 
    pp_row = df[df['Dòng tiền Tích lũy'] >= 0].iloc[0]
    # Lấy năm trước năm hoàn vốn
    year_before_pp = pp_row.name - 1 
    # Tính PP: Năm trước + (Vốn đầu tư còn lại / Dòng tiền năm hoàn vốn)
    # Vốn đầu tư còn lại = Dòng tiền tích lũy năm trước đó * (-1)
    if year_before_pp >= 0:
        I_remaining = -df.loc[year_before_pp, 'Dòng tiền Tích lũy']
        CF_pp_year = df.loc[pp_row.name, 'Dòng tiền']
        PP = year_before_pp + (I_remaining / CF_pp_year)
    else: # Hoàn vốn ngay năm 1
        PP = 0 + (-df.loc[0, 'Dòng tiền Tích lũy']) / df.loc[1, 'Dòng tiền']
        
    # 4. DPP (Discounted Payback Period - Thời gian hoàn vốn có chiết khấu)
    # Lấy Dòng tiền Chiết khấu tích lũy
    dpp_row = df[df['Dòng tiền Chiết khấu Tích lũy'] >= 0].iloc[0]
    year_before_dpp = dpp_row.name - 1
    # Tính DPP: Năm trước + (Vốn đầu tư còn lại chiết khấu / Dòng tiền chiết khấu năm hoàn vốn)
    if year_before_dpp >= 0:
        I_discounted_remaining = -df.loc[year_before_dpp, 'Dòng tiền Chiết khấu Tích lũy']
        DCF_dpp_year = df.loc[dpp_row.name, 'Dòng tiền Chiết khấu']
        DPP = year_before_dpp + (I_discounted_remaining / DCF_dpp_year)
    else: # Hoàn vốn chiết khấu ngay năm 1
        DPP = 0 + (-df.loc[0, 'Dòng tiền Chiết khấu Tích lũy']) / df.loc[1, 'Dòng tiền Chiết khấu']


    return {
        "NPV": NPV,
        "IRR": IRR,
        "PP": PP,
        "DPP": DPP,
        "WACC": r # Lưu lại WACC để so sánh với IRR
    }

# --- Hàm Phân tích AI (Nhiệm vụ 4) ---
@st.cache_data(show_spinner="Đang yêu cầu AI phân tích các chỉ số...")
def get_metrics_analysis(metrics_data, api_key):
    """Gửi các chỉ số đánh giá đến Gemini API và nhận nhận xét."""
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash' 
        
        # Định dạng dữ liệu cho AI
        data_for_ai = {
            "NPV": f"{metrics_data['NPV']:,.0f} VNĐ",
            "IRR": f"{metrics_data['IRR']:.2%}" if not np.isnan(metrics_data['IRR']) else "Không xác định",
            "PP": f"{metrics_data['PP']:.2f} năm",
            "DPP": f"{metrics_data['DPP']:.2f} năm",
            "WACC": f"{metrics_data['WACC']:.2%}"
        }

        prompt = f"""
        Bạn là một chuyên gia thẩm định dự án đầu tư. Dựa trên các chỉ số hiệu quả dự án sau, hãy đưa ra một nhận xét khách quan, ngắn gọn (khoảng 3-4 đoạn) về tính khả thi và rủi ro của dự án. 
        Đánh giá tập trung vào:
        1. Tính chấp nhận được của dự án (dựa trên NPV và so sánh IRR với WACC).
        2. Tốc độ hoàn vốn (dựa trên PP và DPP).
        3. Khuyến nghị tóm tắt.
        
        Các chỉ số dự án:
        {json.dumps(data_for_ai, indent=4)}
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API hoặc giới hạn sử dụng. Chi tiết lỗi: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định: {e}"


# ==============================================================================
# --- GIAO DIỆN CHÍNH CỦA STREAMLIT ---
# ==============================================================================

# --- Cấu hình API Key ---
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.warning("⚠️ Lỗi: Không tìm thấy Khóa API 'GEMINI_API_KEY'. Vui lòng cấu hình trong Streamlit Secrets để sử dụng chức năng AI.")
    API_KEY = None


# --- 1. Tải File Word ---
uploaded_file = st.file_uploader(
    "1. Tải file Word (.docx) chứa Phương án Kinh doanh",
    type=['docx']
)

if uploaded_file is not None and API_KEY:
    
    # Đọc nội dung file
    project_text_content = read_docx(uploaded_file)

    if project_text_content:
        st.info("File Word đã được tải lên thành công. Nội dung đã sẵn sàng để trích xuất.")
        
        # Nút bấm để thực hiện Trích xuất (Nhiệm vụ 1)
        if st.button("▶️ 1. Lọc Dữ liệu Dự án bằng AI"):
            
            # --- 1. Lọc Dữ liệu ---
            project_data = extract_project_data(project_text_content, API_KEY)
            
            if project_data:
                st.session_state['project_data'] = project_data # Lưu vào session state
                st.subheader("✅ Dữ liệu Dự án Đã Lọc (Nhiệm vụ 1)")
                
                # Hiển thị dữ liệu dưới dạng bảng
                data_df = pd.DataFrame(project_data.items(), columns=['Chỉ tiêu', 'Giá trị'])
                data_df['Đơn vị'] = ['VNĐ', 'Năm', 'VNĐ/năm', 'VNĐ/năm', '%', '%', '%']
                data_df['Giá trị'] = data_df.apply(
                    lambda row: f"{row['Giá trị']:,.0f}" if row['Đơn vị'] == 'VNĐ' or row['Đơn vị'] == 'VNĐ/năm' 
                    else f"{row['Giá trị']:.2%}" if row['Đơn vị'] == '%' 
                    else f"{row['Giá trị']:.0f}", axis=1
                )
                st.dataframe(data_df.set_index('Chỉ tiêu'), use_container_width=True)

# Kiểm tra nếu dữ liệu đã được lọc thành công (có trong session state)
if 'project_data' in st.session_state:
    data = st.session_state['project_data']
    
    # --- 2. Xây dựng Bảng Dòng Tiền (Nhiệm vụ 2) ---
    st.subheader("📝 2. Bảng Dòng Tiền Thuần Dự án (NCF)")
    
    try:
        df_cf, WACC = build_cash_flow_table(data)
        st.session_state['df_cf'] = df_cf
        
        # Hiển thị bảng dòng tiền
        st.dataframe(df_cf.style.format({
            'Dòng tiền': '{:,.0f}',
            'Chiết khấu': '{:.4f}',
            'Dòng tiền Chiết khấu': '{:,.0f}',
            'Dòng tiền Tích lũy': '{:,.0f}',
            'Dòng tiền Chiết khấu Tích lũy': '{:,.0f}'
        }), use_container_width=True)

        if 'df_cf' in st.session_state:
            
            # --- 3. Tính toán Chỉ số Đánh giá (Nhiệm vụ 3) ---
            st.subheader("📈 3. Các Chỉ số Đánh giá Hiệu quả Dự án")
            
            metrics = calculate_metrics(df_cf, WACC)
            st.session_state['metrics'] = metrics

            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("Vốn Chiết khấu (WACC)", f"{metrics['WACC']:.2%}")
            with col2:
                st.metric("Giá trị Hiện tại Thuần (NPV)", f"{metrics['NPV']:,.0f} VNĐ")
            with col3:
                st.metric("Tỷ suất Hoàn vốn Nội bộ (IRR)", f"{metrics['IRR']:.2%}" if not np.isnan(metrics['IRR']) else "N/A")
            with col4:
                st.metric("Thời gian Hoàn vốn (PP)", f"{metrics['PP']:.2f} năm")
            with col5:
                st.metric("Thời gian Hoàn vốn có Chiết khấu (DPP)", f"{metrics['DPP']:.2f} năm")

            # --- 4. Yêu cầu AI Phân tích (Nhiệm vụ 4) ---
            if st.button("🔮 4. Yêu cầu AI Phân tích Chỉ số Hiệu quả"):
                if API_KEY and not np.isnan(metrics['IRR']):
                    with st.spinner('Đang gửi dữ liệu và chờ Gemini phân tích...'):
                        ai_result = get_metrics_analysis(metrics, API_KEY)
                        st.markdown("---")
                        st.subheader("✨ Kết quả Phân tích từ Gemini AI:")
                        st.info(ai_result)
                elif np.isnan(metrics['IRR']):
                     st.warning("Không thể tính IRR (dòng tiền không đổi dấu). Vui lòng kiểm tra lại dữ liệu đầu vào.")
                else:
                    st.error("Lỗi: Không tìm thấy Khóa API. Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets.")


    except ValueError as ve:
        st.error(f"Lỗi: {ve}")
    except Exception as e:
        st.error(f"Đã xảy ra lỗi khi tính toán dòng tiền: {e}")
