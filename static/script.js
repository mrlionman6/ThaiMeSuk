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
// แนบภาพ (ต้อง login) — เลือกไฟล์แล้วโชว์ชื่อไฟล์เป็น chip เล็กๆ ใต้ช่องพิมพ์
// =====================================================================
function handleImageSelected() {
    const imageInput = document.getElementById("imageAttachInput");
    const file = imageInput.files[0];
    if (!file) return;

    if (!currentUser) {
        alert("กรุณาเข้าสู่ระบบก่อนใช้ฟีเจอร์แนบภาพ");
        imageInput.value = "";
        return;
    }

    const maxSizeBytes = 5 * 1024 * 1024; // ต้องตรงกับ MAX_IMAGE_SIZE_BYTES ฝั่ง backend
    if (file.size > maxSizeBytes) {
        alert("ไฟล์ภาพใหญ่เกินไป (จำกัดไม่เกิน 5MB)");
        imageInput.value = "";
        return;
    }

    document.getElementById("imageAttachName").textContent = "📎 " + file.name;
    document.getElementById("imageAttachPreview").hidden = false;
}

function clearImageAttachment() {
    document.getElementById("imageAttachInput").value = "";
    document.getElementById("imageAttachPreview").hidden = true;
}

// =====================================================================
// ถาม-ตอบหลัก
// =====================================================================
// =====================================================================
// ขยายช่องพิมพ์เป็น popup กลางจอ — ตอนพิมพ์ยาวเกินกรอบ หรือคลิกกล่องที่มีข้อความยาวค้างอยู่
// =====================================================================
function checkAndExpandInput() {
    const input = document.getElementById("questionInput");
    // scrollWidth > clientWidth แปลว่าข้อความยาวเกินกว่าจะแสดงในกรอบได้หมด (ล้นกรอบ)
    if (input.scrollWidth > input.clientWidth + 2) {
        openInputExpandModal();
    }
}

function handleQuestionInputChange() {
    checkAndExpandInput();
}

function handleQuestionInputClick() {
    checkAndExpandInput();
}

function openInputExpandModal() {
    const currentText = document.getElementById("questionInput").value;
    openModal(`
        <textarea id="questionExpandTextarea" class="input-expand-textarea"
                  placeholder="พิมพ์คำถามเกี่ยวกับกฎหมายที่ท่านสงสัย">${escapeHtml(currentText)}</textarea>
        <div class="ask-controls">
            <button type="button" onclick="document.getElementById('imageAttachInput').click()">แนบเอกสารทางกฎหมาย</button>
            <button onclick="submitFromExpandModal()">ถาม</button>
        </div>
    `, "modal-card-wide");

    const textarea = document.getElementById("questionExpandTextarea");
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length); // เคอร์เซอร์ไปท้ายข้อความเดิม พิมพ์ต่อได้เลย

    // sync ค่ากลับไปที่ input ตัวเดิมทุกครั้งที่พิมพ์ — เพื่อให้พอปิด popup แล้วข้อความยังอยู่ครบ
    // (ปิด popup ไม่ได้ล้างข้อความทิ้ง กดกล่องเดิมใหม่เปิดกลับมาแก้ต่อได้)
    textarea.addEventListener("input", () => {
        document.getElementById("questionInput").value = textarea.value;
    });
}

function submitFromExpandModal() {
    const textarea = document.getElementById("questionExpandTextarea");
    document.getElementById("questionInput").value = textarea.value;
    closeModal();
    askQuestion();
}

// เก็บสถานะ "กำลังรอคำตอบ" แยกตามแชท — ทำให้สลับ tab/แชทระหว่างรอได้โดยไม่งง
// ว่าคำตอบไหนเป็นของแชทไหน และกลับมาแชทเดิมแล้วยังเห็น loading ถ้ายังไม่เสร็จจริงๆ
let pendingChatIds = new Set(); // เก็บ chat_id (number) ที่มีคำถามค้างรอคำตอบอยู่
let pendingNewChat = false;     // true ถ้ามีคำถามที่ยังไม่มี chat_id (เพิ่งเริ่มแชทใหม่) ค้างรออยู่

function isChatPending(chatId) {
    return chatId !== null ? pendingChatIds.has(chatId) : pendingNewChat;
}

function updateLoadingIndicator() {
    document.getElementById("loading").hidden = !isChatPending(currentChatId);
}

function markChatPending(chatId, isPending) {
    if (chatId !== null) {
        if (isPending) pendingChatIds.add(chatId); else pendingChatIds.delete(chatId);
    } else {
        pendingNewChat = isPending;
    }
}

async function askQuestion() {
    const input = document.getElementById("questionInput");
    const query = input.value.trim();
    const imageInput = document.getElementById("imageAttachInput");
    const imageFile = imageInput.files[0] || null;

    if (!query && !imageFile) return;

    // จำแชทที่กำลังถามไว้ ณ ตอนเริ่ม — เผื่อ user สลับไปแชทอื่นระหว่างรอคำตอบ
    // (currentChatId ตัวแปร global อาจเปลี่ยนไปแล้วตอนคำตอบมาถึง ถ้าสลับแชทระหว่างทาง)
    const requestChatId = currentChatId;

    // สร้าง FormData ไว้ก่อนเคลียร์ input (multipart/form-data รองรับทั้งข้อความและไฟล์ในคำขอเดียว)
    const formData = new FormData();
    formData.append("query", query);
    if (requestChatId) formData.append("chat_id", requestChatId);
    if (imageFile) formData.append("image", imageFile);

    // โชว์คำถามทันทีถ้ายังอยู่แชทเดียวกับที่กำลังจะถาม (ควรเป็นเช่นนั้นเสมอตอนกดปุ่ม)
    appendChatMessage("user", query || "📎 (ส่งภาพแนบมาโดยไม่มีข้อความ)");
    input.value = "";
    clearImageAttachment();
    scrollChatToBottom();

    markChatPending(requestChatId, true);
    updateLoadingIndicator();

    try {
        const response = await fetch("/ask", {
            method: "POST",
            body: formData, // ไม่ต้องตั้ง Content-Type เอง browser จัดการ multipart boundary ให้อัตโนมัติ
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || ("HTTP " + response.status));

        markChatPending(requestChatId, false);
        updateLoadingIndicator();

        if (currentUser && data.chat_id) {
            if (currentChatId === requestChatId) {
                currentChatId = data.chat_id; // แชทใหม่เพิ่งได้ id จริงตอนนี้
            }
            loadChatHistory(); // อัปเดต sidebar เสมอ แม้ทำงานอยู่เบื้องหลัง (ไม่ได้ดูแชทนี้ตอนนี้)
        }

        // โชว์คำตอบแบบ "fake streaming" เฉพาะตอนยังอยู่แชทเดียวกับที่ถามไว้เท่านั้น
        // (คำตอบผ่านการเช็ค LanguageGuard มาครบแล้วตั้งแต่ backend ก่อนส่งมาถึงตรงนี้)
        if (currentChatId === requestChatId) {
            const wrapper = document.createElement("div");
            wrapper.className = "chat-msg chat-msg-assistant";
            document.getElementById("answerBox").appendChild(wrapper);
            typewriterReveal(wrapper, data.answer, requestChatId);
        }
        // ถ้าสลับไปแชทอื่นแล้ว ไม่ต้องโชว์อะไร (จะเห็นตอนกลับมาเปิดแชทนั้นผ่าน loadChat ที่ fetch จาก server)

    } catch (error) {
        markChatPending(requestChatId, false);
        updateLoadingIndicator();
        if (currentChatId === requestChatId) {
            appendChatMessage("assistant", "⚠️ เกิดข้อผิดพลาด: " + error);
            scrollChatToBottom();
        }
    }
}

// "Fake streaming" — คำตอบมาครบเต็มแล้วจาก backend (ผ่าน LanguageGuard retry มาแล้ว)
// แค่ทยอย "เผย" ทีละส่วนด้วย JS ให้ดูเหมือนกำลัง generate สดๆ เฉยๆ ไม่ใช่ streaming จริงจาก network
// เลือกใช้วิธีนี้แทน streaming จริง (มี /ask/stream ให้ใช้ได้ถ้าต้องการ) เพื่อรักษาระบบ retry ไว้
// เพราะ retry ทำไม่ได้แล้วถ้าเริ่มโชว์บางส่วนให้ user เห็นไปแล้วผ่าน streaming จริง
function typewriterReveal(wrapper, fullText, requestChatId) {
    let index = 0;
    const chunkSize = 3;   // ตัวอักษรต่อ tick — ปรับตรงนี้เพื่อปรับความเร็วการ "พิมพ์"
    const intervalMs = 15; // ms ต่อ tick

    function tick() {
        // เช็คทุก tick กันกรณี user สลับแชทระหว่างกำลังเผยข้อความอยู่ — หยุดอัปเดตจอทันทีถ้าไม่ได้ดูแชทนี้แล้ว
        if (currentChatId !== requestChatId) return;

        index = Math.min(index + chunkSize, fullText.length);
        const partial = fullText.slice(0, index);
        const rawHtml = marked.parse(partial);
        wrapper.innerHTML = DOMPurify.sanitize(rawHtml);
        scrollChatToBottom();

        if (index < fullText.length) {
            setTimeout(tick, intervalMs);
        }
    }
    tick();
}

// ---------- Helpers สำหรับต่อข้อความเข้ากล่องแชท (ใช้ร่วมกันทั้งถามใหม่และโหลดแชทเก่า) ----------
function appendChatMessage(role, content) {
    const box = document.getElementById("answerBox");
    const wrapper = document.createElement("div");
    wrapper.className = role === "user" ? "chat-msg chat-msg-user" : "chat-msg chat-msg-assistant";

    if (role === "user") {
        wrapper.textContent = content;
        wrapper.classList.add("truncatable"); // ตัด ... ถ้ายาวเกิน 1 บรรทัด กดเพื่อดูเต็มได้
        wrapper.title = "คลิกเพื่อดูข้อความเต็ม";
        wrapper.addEventListener("click", () => wrapper.classList.toggle("expanded"));
    } else {
        const rawHtml = marked.parse(content);
        wrapper.innerHTML = DOMPurify.sanitize(rawHtml);
    }
    box.appendChild(wrapper);
    updateTitleVisibility(); // แชทมีข้อความแล้ว → ซ่อนข้อความทักทายทันที
}

// ข้อความทักทาย "กำลังสงสัยกฎหมายอะไรอยู่?" โชว์เฉพาะตอนแชทว่างเปล่า (ยังไม่มีคำถามเลย)
// หายไปทันทีที่เริ่มมีข้อความในแชท และกลับมาโชว์อีกครั้งตอนกด "แชทใหม่"
function updateTitleVisibility() {
    const title = document.querySelector(".page-title");
    const box = document.getElementById("answerBox");
    if (!title || !box) return;
    title.style.display = box.children.length === 0 ? "" : "none";
}

function scrollChatToBottom() {
    const box = document.getElementById("answerBox");
    box.scrollTop = box.scrollHeight;
}

// =====================================================================
// Sidebar — เปิด/ปิดเมนู
// =====================================================================
function openSidebar() {
    document.getElementById("sideMenu").classList.add("open");
    document.getElementById("sideMenu").setAttribute("aria-hidden", "false");
    document.getElementById("sidebarBackdrop").hidden = false;
    document.getElementById("sidebarToggle").setAttribute("aria-expanded", "true");
    document.getElementById("sidebarToggle").hidden = true; // ซ่อนปุ่มเปิด กันชนกับแถบหัว sidebar ที่มีปุ่มปิด (✕) อยู่แล้ว
}

function closeSidebar() {
    document.getElementById("sideMenu").classList.remove("open");
    document.getElementById("sideMenu").setAttribute("aria-hidden", "true");
    document.getElementById("sidebarBackdrop").hidden = true;
    document.getElementById("sidebarToggle").setAttribute("aria-expanded", "false");
    document.getElementById("sidebarToggle").hidden = false; // เอาปุ่มกลับมาโชว์ตอนปิด sidebar แล้ว
}

document.getElementById("sidebarToggle").addEventListener("click", openSidebar);
document.getElementById("sidebarClose").addEventListener("click", closeSidebar);
let sidebarMouseDownOnBackdrop = false;

document.getElementById("sidebarBackdrop").addEventListener("mousedown", (e) => {
    sidebarMouseDownOnBackdrop = (e.target.id === "sidebarBackdrop");
});

document.getElementById("sidebarBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "sidebarBackdrop" && sidebarMouseDownOnBackdrop) {
        closeSidebar();
    }
    sidebarMouseDownOnBackdrop = false;
});
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeSidebar();
        closeModal();
    }
});

// =====================================================================
// Modal (ใช้ร่วมกัน: login / register / forgot password / profile)
// =====================================================================
function openModal(html, extraClass) {
    const modalContent = document.getElementById("modalContent");
    modalContent.className = "modal-card" + (extraClass ? " " + extraClass : ""); // reset แล้วค่อยเติม class พิเศษ กันค้างจาก modal ก่อนหน้า
    modalContent.innerHTML = html;
    document.getElementById("modalBackdrop").hidden = false;
}

function closeModal() {
    document.getElementById("modalBackdrop").hidden = true;
    document.getElementById("modalContent").innerHTML = "";
    document.getElementById("modalContent").className = "modal-card"; // reset กลับค่าเริ่มต้นเสมอ
}

// popup ยืนยันแบบเดียวกับดีไซน์เว็บ (แทน browser confirm() เดิมที่หน้าตาไม่เข้ากับแอป)
// ใช้แบบ callback เพราะ modal เปิดแบบ async ไม่ block โค้ดต่อจากนี้เหมือน confirm() ของ browser
function showConfirmDialog(message, onConfirm, options = {}) {
    const confirmText = options.confirmText || "ตกลง";
    const cancelText = options.cancelText || "ยกเลิก";
    const onCancel = options.onCancel || closeModal; // ปกติกด "ยกเลิก" แล้วปิด modal เฉยๆ แต่บาง flow (เช่นลบบัญชีจากหน้าโปรไฟล์) อยากกลับไป modal เดิมแทน

    openModal(`
        <p class="confirm-dialog-message">${escapeHtml(message)}</p>
        <div class="modal-buttons">
            <button type="button" id="confirmDialogCancelBtn">${escapeHtml(cancelText)}</button>
            <button type="button" id="confirmDialogOkBtn" class="danger-btn">${escapeHtml(confirmText)}</button>
        </div>
    `);

    document.getElementById("confirmDialogOkBtn").onclick = () => {
        closeModal();
        onConfirm();
    };
    document.getElementById("confirmDialogCancelBtn").onclick = onCancel;
}

// เช็คทั้ง mousedown และ click ต้องเกิดบน backdrop เดียวกัน ถึงจะปิด modal
// (ถ้าเช็คแค่ click อย่างเดียว: ลาก select ข้อความในกล่องแล้วปล่อยเมาส์นอกกล่อง
// จะถูกนับเป็น "คลิกที่ backdrop" ทั้งที่ตั้งใจแค่ลากเลือกข้อความ ไม่ได้ตั้งใจปิด)
let modalMouseDownOnBackdrop = false;

document.getElementById("modalBackdrop").addEventListener("mousedown", (e) => {
    modalMouseDownOnBackdrop = (e.target.id === "modalBackdrop");
});

document.getElementById("modalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "modalBackdrop" && modalMouseDownOnBackdrop) {
        closeModal();
    }
    modalMouseDownOnBackdrop = false;
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
                <div class="captcha-img-wrapper">
                    <img id="captchaImg" src="/api/auth/captcha" alt="รหัสยืนยันภาพ">
                    <div id="captchaSpinner" class="captcha-spinner" hidden></div>
                </div>
                <button type="button" id="captchaRefreshBtn" onclick="refreshCaptcha()" class="captcha-refresh-btn">สุ่มใหม่</button>
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
    const img = document.getElementById("captchaImg");
    const spinner = document.getElementById("captchaSpinner");
    const btn = document.getElementById("captchaRefreshBtn");

    btn.disabled = true; // กันกดซ้ำระหว่างกำลังโหลดภาพใหม่
    spinner.hidden = false;

    // preload ภาพใหม่แบบ offscreen ก่อน ค่อยสลับ src จริงตอนโหลดเสร็จ
    // กันเห็นภาพโหลดครึ่งๆ กลางๆ หรือภาพแตกระหว่างรอ
    const preload = new Image();
    preload.onload = () => {
        img.src = preload.src;
        spinner.hidden = true;
        btn.disabled = false;
    };
    preload.onerror = () => {
        spinner.hidden = true;
        btn.disabled = false;
        alert("โหลดภาพยืนยันไม่สำเร็จ ลองใหม่อีกครั้ง");
    };
    preload.src = "/api/auth/captcha?t=" + Date.now(); // กัน browser cache ภาพเดิม
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

function handleDeleteAccount() {
    const password = document.getElementById("deleteAccountPassword").value;
    const statusEl = document.getElementById("deleteStatus");

    if (!password) {
        statusEl.textContent = "กรอกรหัสผ่านเพื่อยืนยัน";
        statusEl.style.color = "red";
        return;
    }

    showConfirmDialog(
        "ยืนยันลบบัญชีถาวร? ข้อมูลทั้งหมดจะหายและกู้คืนไม่ได้",
        async () => {
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
                alert("ลบบัญชีไม่สำเร็จ: " + error);
            }
        },
        { onCancel: () => openProfileModal() } // กด "ยกเลิก" กลับไปหน้าโปรไฟล์เดิม ไม่ใช่ปิด modal ทั้งหมด
    );
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
        updateLoadingIndicator(); // ถ้าแชทนี้ยังมีคำถามค้างรอคำตอบอยู่ (ถามไว้ตอนอยู่แชทอื่น) ให้โชว์ loading กลับมา
        loadChatHistory();
        closeSidebar();
    } catch (error) {
        alert("โหลดแชทไม่สำเร็จ: " + error);
    }
}

function handleDeleteChat(chatId) {
    showConfirmDialog("ลบแชทนี้ถาวร?", async () => {
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
    });
}

function renderChatTranscript(messages) {
    const box = document.getElementById("answerBox");
    box.innerHTML = "";
    messages.forEach(msg => appendChatMessage(msg.role, msg.content));
    updateTitleVisibility(); // เผื่อกรณี messages ว่างเปล่า (edge case) ให้ title โชว์ถูกต้อง
    scrollChatToBottom();
}

function startNewChat() {
    currentChatId = null;
    document.getElementById("answerBox").innerHTML = "";
    document.getElementById("questionInput").value = "";
    updateTitleVisibility(); // แชทว่างแล้ว → โชว์ข้อความทักทายกลับมา
    updateLoadingIndicator(); // เผื่อมีคำถามใหม่ (ที่ยังไม่มี id) ค้างรออยู่ตอนกด "แชทใหม่" ซ้อนอีกที
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
