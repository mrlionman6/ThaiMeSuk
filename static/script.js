// =====================================================================
// State
// =====================================================================
let currentUser = null;      // null = ยังไม่ login, หรือ {id, email}
let currentChatId = null;    // แชทที่กำลังเปิดอยู่ (null = ยังไม่มี/เริ่มแชทใหม่)

// =====================================================================
// ถาม-ตอบหลัก
// =====================================================================
async function askQuestion() {
    const input = document.getElementById("questionInput");
    const query = input.value.trim();
    if (!query) return;

    document.getElementById("loading").style.display = "block";

    try {
        const response = await fetch("/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query, chat_id: currentChatId })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || ("HTTP " + response.status));

        document.getElementById("loading").style.display = "none";
        const rawHtml = marked.parse(data.answer);
        const cleanHtml = DOMPurify.sanitize(rawHtml);
        document.getElementById("answerBox").innerHTML = cleanHtml;
        input.value = "";

        // ถ้า login อยู่ backend จะสร้าง/อัปเดตแชทให้เสมอ (ดู /ask ใน main.py) — sync state กลับมา
        if (currentUser && data.chat_id) {
            currentChatId = data.chat_id;
            loadChatHistory(); // รีเฟรชไซด์บาร์ ให้เห็นแชทใหม่/อัปเดตล่าสุดขึ้นบนสุด
        }

    } catch (error) {
        document.getElementById("loading").style.display = "none";
        document.getElementById("answerBox").innerText = "เกิดข้อผิดพลาด: " + error;
    }
}

// =====================================================================
// Sidebar — เปิด/ปิดเมนู
// =====================================================================
function openSidebar() {
    document.getElementById("sideMenu").classList.add("open");
    document.getElementById("sideMenu").setAttribute("aria-hidden", "false");
    document.getElementById("sidebarBackdrop").hidden = false;
    document.getElementById("sidebarToggle").setAttribute("aria-expanded", "true");
}

function closeSidebar() {
    document.getElementById("sideMenu").classList.remove("open");
    document.getElementById("sideMenu").setAttribute("aria-hidden", "true");
    document.getElementById("sidebarBackdrop").hidden = true;
    document.getElementById("sidebarToggle").setAttribute("aria-expanded", "false");
}

document.getElementById("sidebarToggle").addEventListener("click", openSidebar);
document.getElementById("sidebarClose").addEventListener("click", closeSidebar);
document.getElementById("sidebarBackdrop").addEventListener("click", closeSidebar);
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidebar();
});

// =====================================================================
// Auth — เช็คสถานะตอนโหลดหน้า + login/register/logout
// =====================================================================
async function checkAuthStatus() {
    try {
        const res = await fetch("/api/auth/me");
        const data = await res.json();
        currentUser = data.logged_in ? data.user : null;
    } catch (error) {
        currentUser = null;
    }
    renderUserArea();
    if (currentUser) {
        loadChatHistory();
    }
}

function renderUserArea() {
    const container = document.getElementById("userArea");

    if (currentUser) {
        container.innerHTML = `
            <div class="side-user-info">
                <span class="side-user-email">${escapeHtml(currentUser.email)}</span>
                <button class="side-signout-btn" onclick="handleSignOut()">ออกจากระบบ</button>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="side-auth-buttons">
                <button onclick="showAuthForm('login')">เข้าสู่ระบบ</button>
                <button onclick="showAuthForm('register')">สมัครสมาชิก</button>
            </div>
        `;
    }
}

function showAuthForm(mode) {
    // mode: "login" หรือ "register" — โชว์ฟอร์มแทนที่ปุ่ม 2 ปุ่มชั่วคราว
    const container = document.getElementById("userArea");
    const isLogin = mode === "login";

    container.innerHTML = `
        <form id="authForm" class="side-auth-form">
            <input type="email" id="authEmail" placeholder="อีเมล" required>
            <input type="password" id="authPassword" placeholder="รหัสผ่าน (อย่างน้อย 8 ตัวอักษร)" required minlength="8">
            <div class="side-auth-form-buttons">
                <button type="submit">${isLogin ? "เข้าสู่ระบบ" : "สมัครสมาชิก"}</button>
                <button type="button" onclick="renderUserArea()">ยกเลิก</button>
            </div>
            <span id="authFormError" class="side-auth-error"></span>
        </form>
    `;

    document.getElementById("authForm").addEventListener("submit", (e) => {
        e.preventDefault();
        if (isLogin) {
            handleLogin();
        } else {
            handleRegister();
        }
    });
}

async function handleLogin() {
    const email = document.getElementById("authEmail").value.trim();
    const password = document.getElementById("authPassword").value;
    const errorEl = document.getElementById("authFormError");

    try {
        const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "เข้าสู่ระบบไม่สำเร็จ");

        currentUser = data.user;
        renderUserArea();
        loadChatHistory();
    } catch (error) {
        errorEl.textContent = String(error.message || error);
    }
}

async function handleRegister() {
    const email = document.getElementById("authEmail").value.trim();
    const password = document.getElementById("authPassword").value;
    const errorEl = document.getElementById("authFormError");

    try {
        const res = await fetch("/api/auth/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "สมัครสมาชิกไม่สำเร็จ");

        currentUser = data.user;
        renderUserArea();
        loadChatHistory();
    } catch (error) {
        errorEl.textContent = String(error.message || error);
    }
}

async function handleSignOut() {
    try {
        await fetch("/api/auth/logout", { method: "POST" });
    } catch (error) {
        // ถึง logout ฝั่ง server จะพลาด ก็เคลียร์ฝั่ง client ต่อไปได้เลย ไม่ต้องบล็อกผู้ใช้
    }
    currentUser = null;
    currentChatId = null;
    renderUserArea();
    resetChatHistoryUI();
    document.getElementById("answerBox").innerHTML = "";
}

// =====================================================================
// ประวัติแชท (กลาง sidebar)
// =====================================================================
function resetChatHistoryUI() {
    document.getElementById("chatHistoryList").innerHTML =
        '<li class="side-empty">เข้าสู่ระบบเพื่อบันทึกประวัติแชท</li>';
}

async function loadChatHistory() {
    if (!currentUser) return;

    const list = document.getElementById("chatHistoryList");
    try {
        const res = await fetch("/api/chats");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        if (data.chats.length === 0) {
            list.innerHTML = '<li class="side-empty">ยังไม่มีประวัติแชท</li>';
            return;
        }

        list.innerHTML = "";
        data.chats.forEach(chat => {
            const li = document.createElement("li");
            li.textContent = chat.title;
            li.title = chat.title; // full title ตอน hover เผื่อชื่อยาวถูกตัด
            if (chat.id === currentChatId) li.classList.add("side-chat-active");
            li.onclick = () => loadChat(chat.id);
            list.appendChild(li);
        });
    } catch (error) {
        list.innerHTML = '<li class="side-empty">โหลดประวัติแชทไม่สำเร็จ</li>';
    }
}

async function loadChat(chatId) {
    try {
        const res = await fetch("/api/chats/" + chatId);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        currentChatId = chatId;
        renderChatTranscript(data.messages);
        loadChatHistory(); // รีเฟรชให้ highlight แชทที่กำลังเปิดอยู่
        closeSidebar();
    } catch (error) {
        alert("โหลดแชทไม่สำเร็จ: " + error);
    }
}

function renderChatTranscript(messages) {
    // แสดงประวัติทั้งแชทเป็นลำดับคำถาม-คำตอบ (ต่างจาก /ask ปกติที่โชว์แค่คำตอบล่าสุด)
    const box = document.getElementById("answerBox");
    box.innerHTML = "";

    messages.forEach(msg => {
        const wrapper = document.createElement("div");
        wrapper.className = msg.role === "user" ? "chat-msg chat-msg-user" : "chat-msg chat-msg-assistant";

        if (msg.role === "user") {
            wrapper.textContent = msg.content;
        } else {
            const rawHtml = marked.parse(msg.content);
            wrapper.innerHTML = DOMPurify.sanitize(rawHtml);
        }
        box.appendChild(wrapper);
    });
}

function startNewChat() {
    currentChatId = null;
    document.getElementById("answerBox").innerHTML = "";
    document.getElementById("questionInput").value = "";
    loadChatHistory(); // เอา highlight แชทเดิมออก
    closeSidebar();
}

// =====================================================================
// Helpers
// =====================================================================
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// =====================================================================
// Init
// =====================================================================
checkAuthStatus();
