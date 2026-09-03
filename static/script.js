// =====================================================================
// State
// =====================================================================
let currentUser = null;          // null = ยังไม่ login, หรือ {id, username, nickname, role}
let currentChatId = null;        // แชทที่กำลังเปิดอยู่ (null = ยังไม่มี/เริ่มแชทใหม่)
let securityQuestionsCache = null; // cache รายการคำถามทั้ง 10 ข้อ (ดึงครั้งเดียว)
let forgotPasswordQuestions = null; // 2 คำถามที่สุ่มมาระหว่าง flow ลืมรหัสผ่าน (เก็บไว้ใช้ตอน submit)
let forgotPasswordUsername = null;
const ROLE_LABELS_JS = { 1: "ระดับ 1", 2: "ระดับ 2", 3: "ระดับ 3" };

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

        if (currentUser && data.chat_id) {
            currentChatId = data.chat_id;
            loadChatHistory();
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
    if (e.key === "Escape") {
        closeSidebar();
        closeModal();
    }
});

// =====================================================================
// Modal (ใช้ร่วมกัน: login / register / forgot password / profile)
// =====================================================================
function openModal(html) {
    document.getElementById("modalContent").innerHTML = html;
    document.getElementById("modalBackdrop").hidden = false;
}

function closeModal() {
    document.getElementById("modalBackdrop").hidden = true;
    document.getElementById("modalContent").innerHTML = "";
}

document.getElementById("modalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "modalBackdrop") closeModal();
});

// =====================================================================
// Auth — เช็คสถานะตอนโหลดหน้า
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
                <span class="side-user-email">${escapeHtml(currentUser.nickname || currentUser.username)}</span>
                <div class="side-user-buttons">
                    <button onclick="openProfileModal()">โปรไฟล์</button>
                    <button class="side-signout-btn" onclick="handleSignOut()">ออกจากระบบ</button>
                </div>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="side-auth-buttons">
                <button onclick="openLoginModal()">เข้าสู่ระบบ</button>
                <button onclick="openRegisterModal()">สมัครสมาชิก</button>
            </div>
        `;
    }
}

async function handleSignOut() {
    try {
        await fetch("/api/auth/logout", { method: "POST" });
    } catch (error) {
        // logout ฝั่ง server พลาดก็ยังเคลียร์ฝั่ง client ต่อได้ ไม่บล็อกผู้ใช้
    }
    currentUser = null;
    currentChatId = null;
    renderUserArea();
    resetChatHistoryUI();
    document.getElementById("answerBox").innerHTML = "";
}

// ---------- ดึงรายการ security questions (cache ไว้ ไม่ต้องดึงซ้ำ) ----------
async function getSecurityQuestions() {
    if (securityQuestionsCache) return securityQuestionsCache;
    const res = await fetch("/api/auth/security-questions");
    const data = await res.json();
    securityQuestionsCache = data.questions;
    return securityQuestionsCache;
}

// =====================================================================
// Login modal
// =====================================================================
function openLoginModal() {
    openModal(`
        <h2>เข้าสู่ระบบ</h2>
        <form id="loginForm">
            <input type="text" id="loginUsername" placeholder="ชื่อผู้ใช้" required>
            <input type="password" id="loginPassword" placeholder="รหัสผ่าน" required>
            <div class="modal-error" id="loginError"></div>
            <div class="modal-buttons">
                <button type="submit">เข้าสู่ระบบ</button>
                <button type="button" onclick="closeModal()">ยกเลิก</button>
            </div>
            <p class="modal-link"><a href="#" onclick="openForgotPasswordModal(); return false;">ลืมรหัสผ่าน?</a></p>
        </form>
    `);

    document.getElementById("loginForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const username = document.getElementById("loginUsername").value.trim();
        const password = document.getElementById("loginPassword").value;
        const errorEl = document.getElementById("loginError");

        try {
            const res = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "เข้าสู่ระบบไม่สำเร็จ");

            currentUser = data.user;
            closeModal();
            renderUserArea();
            loadChatHistory();
        } catch (error) {
            errorEl.textContent = String(error.message || error);
        }
    });
}

// =====================================================================
// Register modal — nickname + username + password + role + CAPTCHA + เลือกตอบ 5 จาก 10 คำถาม
// =====================================================================
async function openRegisterModal() {
    const questions = await getSecurityQuestions();

    const questionsHtml = questions.map(q => `
        <div class="security-question-row">
            <label>
                <input type="checkbox" class="sq-checkbox" data-qid="${q.id}" onchange="toggleSecurityAnswerInput(${q.id})">
                ${escapeHtml(q.text)}
            </label>
            <input type="text" class="sq-answer-input" id="sq-answer-${q.id}" placeholder="คำตอบ" disabled>
        </div>
    `).join("");

    openModal(`
        <h2>สมัครสมาชิก</h2>
        <form id="registerForm">
            <input type="text" id="regNickname" placeholder="ชื่อเล่น (nickname)" required>
            <input type="text" id="regUsername" placeholder="ชื่อผู้ใช้ (อย่างน้อย 3 ตัวอักษร)" required minlength="3">
            <input type="password" id="regPassword" placeholder="รหัสผ่าน (อย่างน้อย 8 ตัวอักษร)" required minlength="8">

            <p class="modal-section-label">ขอสิทธิ์การใช้งานระดับ</p>
            <select id="regRequestedRole">
                <option value="1">ระดับ 1</option>
                <option value="2">ระดับ 2</option>
                <option value="3">ระดับ 3</option>
            </select>
            <p class="modal-hint-note">แอดมินจะเป็นผู้อนุมัติคำขอและกำหนดสิทธิ์จริงให้ ซึ่งอาจไม่ตรงกับที่ขอไว้</p>

            <p class="modal-section-label">ยืนยันว่าไม่ใช่บอท</p>
            <div class="captcha-row">
                <img id="captchaImg" src="/api/auth/captcha" alt="รหัสยืนยันภาพ">
                <button type="button" onclick="refreshCaptcha()" class="captcha-refresh-btn" title="เปลี่ยนภาพใหม่">🔄</button>
            </div>
            <input type="text" id="regCaptchaAnswer" placeholder="พิมพ์ตัวอักษร/ตัวเลขที่เห็นในภาพ" required>

            <p class="modal-section-label">เลือกตอบคำถามกันลืมรหัสผ่าน 5 ข้อ (เลือกแล้ว: <span id="sqCount">0</span>/5)</p>
            <div id="securityQuestionsList">${questionsHtml}</div>

            <div class="modal-error" id="registerError"></div>
            <div class="modal-buttons">
                <button type="submit">ส่งคำขอสมัคร</button>
                <button type="button" onclick="closeModal()">ยกเลิก</button>
            </div>
        </form>
    `);

    document.getElementById("registerForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById("registerError");

        const checked = Array.from(document.querySelectorAll(".sq-checkbox:checked"));
        if (checked.length !== 5) {
            errorEl.textContent = "กรุณาเลือกคำถามให้ครบ 5 ข้อ";
            return;
        }

        const securityAnswers = checked.map(cb => {
            const qid = parseInt(cb.dataset.qid, 10);
            const answer = document.getElementById("sq-answer-" + qid).value.trim();
            return { question_id: qid, answer };
        });

        if (securityAnswers.some(a => !a.answer)) {
            errorEl.textContent = "กรุณาตอบคำถามที่เลือกไว้ให้ครบทุกข้อ";
            return;
        }

        const body = {
            nickname: document.getElementById("regNickname").value.trim(),
            username: document.getElementById("regUsername").value.trim(),
            password: document.getElementById("regPassword").value,
            requested_role: parseInt(document.getElementById("regRequestedRole").value, 10),
            captcha_answer: document.getElementById("regCaptchaAnswer").value,
            security_answers: securityAnswers,
        };

        try {
            const res = await fetch("/api/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            if (!res.ok) {
                refreshCaptcha(); // captcha ใช้ครั้งเดียวถูกลบไปแล้วฝั่ง server ไม่ว่าจะสำเร็จหรือพลาด ต้องขอภาพใหม่เสมอ
                throw new Error(data.detail || "สมัครสมาชิกไม่สำเร็จ");
            }

            closeModal();
            alert("ส่งคำขอสมัครสมาชิกเรียบร้อยแล้ว กรุณารอผู้ดูแลระบบอนุมัติก่อนเข้าสู่ระบบ");
        } catch (error) {
            errorEl.textContent = String(error.message || error);
        }
    });
}

function refreshCaptcha() {
    document.getElementById("captchaImg").src = "/api/auth/captcha?t=" + Date.now(); // กัน browser cache ภาพเดิม
}

function toggleSecurityAnswerInput(questionId) {
    const checkbox = document.querySelector(`.sq-checkbox[data-qid="${questionId}"]`);
    const input = document.getElementById("sq-answer-" + questionId);
    input.disabled = !checkbox.checked;
    if (!checkbox.checked) input.value = "";

    const checkedCount = document.querySelectorAll(".sq-checkbox:checked").length;
    document.getElementById("sqCount").textContent = checkedCount;

    document.querySelectorAll(".sq-checkbox").forEach(cb => {
        if (!cb.checked) cb.disabled = checkedCount >= 5;
    });
}

// =====================================================================
// Forgot password modal — 2 ขั้นตอน
// =====================================================================
function openForgotPasswordModal() {
    openModal(`
        <h2>ลืมรหัสผ่าน</h2>
        <form id="forgotStep1Form">
            <input type="text" id="forgotUsername" placeholder="ชื่อผู้ใช้ที่ใช้สมัคร" required>
            <div class="modal-error" id="forgotStep1Error"></div>
            <div class="modal-buttons">
                <button type="submit">ถัดไป</button>
                <button type="button" onclick="closeModal()">ยกเลิก</button>
            </div>
        </form>
    `);

    document.getElementById("forgotStep1Form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const username = document.getElementById("forgotUsername").value.trim();
        const errorEl = document.getElementById("forgotStep1Error");

        try {
            const res = await fetch("/api/auth/forgot-password/questions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "ไม่พบบัญชีนี้");

            forgotPasswordUsername = username;
            forgotPasswordQuestions = data.questions;
            openForgotStep2Modal();
        } catch (error) {
            errorEl.textContent = String(error.message || error);
        }
    });
}

function openForgotStep2Modal() {
    const questionsHtml = forgotPasswordQuestions.map(q => `
        <input type="text" class="forgot-answer-input" data-qid="${q.id}"
               placeholder="${escapeHtml(q.text)}" required>
    `).join("");

    openModal(`
        <h2>ตอบคำถามยืนยันตัวตน</h2>
        <form id="forgotStep2Form">
            ${questionsHtml}
            <input type="password" id="forgotNewPassword" placeholder="รหัสผ่านใหม่ (อย่างน้อย 8 ตัวอักษร)" required minlength="8">
            <div class="modal-error" id="forgotStep2Error"></div>
            <div class="modal-buttons">
                <button type="submit">ตั้งรหัสผ่านใหม่</button>
                <button type="button" onclick="closeModal()">ยกเลิก</button>
            </div>
        </form>
    `);

    document.getElementById("forgotStep2Form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById("forgotStep2Error");

        const answers = Array.from(document.querySelectorAll(".forgot-answer-input")).map(input => ({
            question_id: parseInt(input.dataset.qid, 10),
            answer: input.value.trim(),
        }));
        const newPassword = document.getElementById("forgotNewPassword").value;

        try {
            const res = await fetch("/api/auth/forgot-password/reset", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: forgotPasswordUsername, answers, new_password: newPassword })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "ตั้งรหัสผ่านใหม่ไม่สำเร็จ");

            forgotPasswordUsername = null;
            forgotPasswordQuestions = null;
            closeModal();
            alert("ตั้งรหัสผ่านใหม่สำเร็จ กรุณาเข้าสู่ระบบด้วยรหัสผ่านใหม่");
            openLoginModal();
        } catch (error) {
            errorEl.textContent = String(error.message || error);
        }
    });
}

// =====================================================================
// Profile modal
// =====================================================================
function openProfileModal() {
    openModal(`
        <h2>โปรไฟล์</h2>
        <p class="modal-email-display">${escapeHtml(currentUser.username)} · ${ROLE_LABELS_JS[currentUser.role] || "ไม่มีระดับสิทธิ์"}</p>

        <div class="profile-section">
            <p class="modal-section-label">ชื่อเล่น</p>
            <input type="text" id="profileNickname" value="${escapeHtml(currentUser.nickname || "")}">
            <button onclick="handleUpdateNickname()">บันทึกชื่อเล่น</button>
            <span id="nicknameStatus" class="modal-status"></span>
        </div>

        <div class="profile-section">
            <p class="modal-section-label">เปลี่ยนรหัสผ่าน</p>
            <input type="password" id="currentPassword" placeholder="รหัสผ่านปัจจุบัน">
            <input type="password" id="newPassword" placeholder="รหัสผ่านใหม่ (อย่างน้อย 8 ตัวอักษร)">
            <button onclick="handleChangePassword()">เปลี่ยนรหัสผ่าน</button>
            <span id="passwordStatus" class="modal-status"></span>
        </div>

        <div class="profile-section profile-danger">
            <p class="modal-section-label">ลบบัญชี</p>
            <p class="modal-danger-note">ลบแล้วข้อมูลทั้งหมด (ประวัติแชท คำถามกันลืมรหัสผ่าน) จะหายถาวร กู้คืนไม่ได้</p>
            <input type="password" id="deleteAccountPassword" placeholder="กรอกรหัสผ่านเพื่อยืนยัน">
            <button onclick="handleDeleteAccount()" class="danger-btn">ลบบัญชีถาวร</button>
            <span id="deleteStatus" class="modal-status"></span>
        </div>

        <div class="modal-buttons">
            <button type="button" onclick="closeModal()">ปิด</button>
        </div>
    `);
}

async function handleUpdateNickname() {
    const nickname = document.getElementById("profileNickname").value.trim();
    const statusEl = document.getElementById("nicknameStatus");

    if (!nickname) {
        statusEl.textContent = "ชื่อเล่นห้ามว่างเปล่า";
        statusEl.style.color = "red";
        return;
    }

    try {
        const res = await fetch("/api/auth/update-nickname", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nickname })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "บันทึกไม่สำเร็จ");

        currentUser.nickname = nickname;
        renderUserArea();
        statusEl.textContent = "✅ บันทึกแล้ว";
        statusEl.style.color = "green";
    } catch (error) {
        statusEl.textContent = "❌ " + error;
        statusEl.style.color = "red";
    }
}

async function handleChangePassword() {
    const currentPassword = document.getElementById("currentPassword").value;
    const newPassword = document.getElementById("newPassword").value;
    const statusEl = document.getElementById("passwordStatus");

    if (newPassword.length < 8) {
        statusEl.textContent = "รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร";
        statusEl.style.color = "red";
        return;
    }

    try {
        const res = await fetch("/api/auth/change-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "เปลี่ยนรหัสผ่านไม่สำเร็จ");

        document.getElementById("currentPassword").value = "";
        document.getElementById("newPassword").value = "";
        statusEl.textContent = "✅ เปลี่ยนรหัสผ่านสำเร็จ";
        statusEl.style.color = "green";
    } catch (error) {
        statusEl.textContent = "❌ " + error;
        statusEl.style.color = "red";
    }
}

async function handleDeleteAccount() {
    const password = document.getElementById("deleteAccountPassword").value;
    const statusEl = document.getElementById("deleteStatus");

    if (!password) {
        statusEl.textContent = "กรอกรหัสผ่านเพื่อยืนยัน";
        statusEl.style.color = "red";
        return;
    }

    if (!confirm("ยืนยันลบบัญชีถาวร? ข้อมูลทั้งหมดจะหายและกู้คืนไม่ได้")) return;

    try {
        const res = await fetch("/api/auth/account", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "ลบบัญชีไม่สำเร็จ");

        currentUser = null;
        currentChatId = null;
        closeModal();
        renderUserArea();
        resetChatHistoryUI();
        document.getElementById("answerBox").innerHTML = "";
        alert("ลบบัญชีเรียบร้อยแล้ว");
    } catch (error) {
        statusEl.textContent = "❌ " + error;
        statusEl.style.color = "red";
    }
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
            li.className = "side-chat-item";
            li.title = chat.title;
            if (chat.id === currentChatId) li.classList.add("side-chat-active");

            const titleSpan = document.createElement("span");
            titleSpan.className = "side-chat-title";
            titleSpan.textContent = chat.title;
            titleSpan.onclick = () => loadChat(chat.id);

            const deleteBtn = document.createElement("button");
            deleteBtn.className = "side-chat-delete";
            deleteBtn.textContent = "✕";
            deleteBtn.title = "ลบแชทนี้";
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                handleDeleteChat(chat.id);
            };

            li.appendChild(titleSpan);
            li.appendChild(deleteBtn);
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
        loadChatHistory();
        closeSidebar();
    } catch (error) {
        alert("โหลดแชทไม่สำเร็จ: " + error);
    }
}

async function handleDeleteChat(chatId) {
    if (!confirm("ลบแชทนี้ถาวร?")) return;

    try {
        const res = await fetch("/api/chats/" + chatId, { method: "DELETE" });
        if (!res.ok) throw new Error("HTTP " + res.status);

        if (currentChatId === chatId) {
            currentChatId = null;
            document.getElementById("answerBox").innerHTML = "";
        }
        loadChatHistory();
    } catch (error) {
        alert("ลบแชทไม่สำเร็จ: " + error);
    }
}

function renderChatTranscript(messages) {
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
    loadChatHistory();
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
