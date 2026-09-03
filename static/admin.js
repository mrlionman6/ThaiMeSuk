// ---------- Tab switching ----------
let currentTab = "pending"; // จำแท็บที่เปิดอยู่ตลอด session ของหน้า (ไม่ผูกกับ URL เพราะไม่ reload หน้า)

// ---------- Pagination state (แยกกันคนละแท็บ) ----------
let pendingPage = 1;
let pendingPageSize = 10;

let kbPage = 1;
let kbPageSize = 10;

let userRequestsPage = 1;
let userRequestsPageSize = 10;

let usersPage = 1;
let usersPageSize = 10;

const PAGE_SIZE_OPTIONS = [10, 20, 50];
const ROLE_LABELS = { 1: "ระดับ 1", 2: "ระดับ 2", 3: "ระดับ 3" };

function switchTab(tab) {
    currentTab = tab;

    document.getElementById("tabPending").style.display = tab === "pending" ? "block" : "none";
    document.getElementById("tabKb").style.display = tab === "kb" ? "block" : "none";
    document.getElementById("tabUserRequests").style.display = tab === "userRequests" ? "block" : "none";
    document.getElementById("tabUsers").style.display = tab === "users" ? "block" : "none";

    document.getElementById("tabBtnPending").classList.toggle("tab-btn-active", tab === "pending");
    document.getElementById("tabBtnKb").classList.toggle("tab-btn-active", tab === "kb");
    document.getElementById("tabBtnUserRequests").classList.toggle("tab-btn-active", tab === "userRequests");
    document.getElementById("tabBtnUsers").classList.toggle("tab-btn-active", tab === "users");

    if (tab === "pending") {
        loadLogs(pendingPage);
    } else if (tab === "kb") {
        loadKb(kbPage);
    } else if (tab === "userRequests") {
        loadUserRequests(userRequestsPage);
    } else if (tab === "users") {
        loadUsers(usersPage);
    }
}

// ---------- แท็บ 1: คำถามรอตรวจสอบ ----------
async function loadLogs(page = 1) {
    pendingPage = page;
    const container = document.getElementById("logsContainer");
    try {
        const response = await fetch(`/admin/api/logs?page=${page}&page_size=${pendingPageSize}`);
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();

        renderPagination("logsPagination", data.total, page, pendingPageSize, (newPage) => loadLogs(newPage), (newSize) => {
            pendingPageSize = newSize;
            loadLogs(1);
        });

        if (data.logs.length === 0) {
            container.innerHTML = page === 1
                ? "<p>ไม่มีรายการรอตรวจสอบ 🎉</p>"
                : "<p>ไม่มีรายการในหน้านี้</p>";
            return;
        }

        container.innerHTML = "";
        data.logs.forEach(log => {
            const div = document.createElement("div");
            div.className = "card";
            div.id = "log-" + log.id;
            div.innerHTML = `
                <p><strong>คำถาม:</strong> ${escapeHtml(log.query)}</p>
                <p><strong>คำตอบที่ Claude ตอบ:</strong> ${escapeHtml(log.answer)}</p>
                <p><strong>คะแนนความมั่นใจ:</strong> ${log.max_score.toFixed(3)}</p>
                <button onclick="approveLog(${log.id})">✅ เพิ่มเข้า Knowledge Base</button>
                <button onclick="rejectLog(${log.id})">❌ ทิ้งไป</button>
            `;
            container.appendChild(div);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลดรายการไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

async function approveLog(id) {
    removeCardOptimistically("log-" + id); // ลบการ์ดออกจากจอทันที ไม่ต้องรอ backend ตอบ
    try {
        const res = await fetch("/admin/api/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ log_id: id })
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("เพิ่มเข้า Knowledge Base ไม่สำเร็จ: " + error + " — กำลังโหลดรายการใหม่");
    } finally {
        loadLogs(pendingPage); // ซิงก์กับ backend เสมอ อยู่หน้าเดิม
    }
}

async function rejectLog(id) {
    removeCardOptimistically("log-" + id);
    try {
        const res = await fetch("/admin/api/reject", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ log_id: id })
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("ทิ้งรายการไม่สำเร็จ: " + error + " — กำลังโหลดรายการใหม่");
    } finally {
        loadLogs(pendingPage);
    }
}

// ---------- แท็บ 2: จัดการ Knowledge Base ----------
async function loadKb(page = 1) {
    kbPage = page;
    const container = document.getElementById("kbContainer");
    try {
        const response = await fetch(`/admin/api/kb?page=${page}&page_size=${kbPageSize}`);
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();

        renderPagination("kbPagination", data.total, page, kbPageSize, (newPage) => loadKb(newPage), (newSize) => {
            kbPageSize = newSize;
            loadKb(1);
        });

        if (data.chunks.length === 0) {
            container.innerHTML = page === 1
                ? "<p>ยังไม่มีข้อมูลใน Knowledge Base</p>"
                : "<p>ไม่มีรายการในหน้านี้</p>";
            return;
        }

        container.innerHTML = `<p style="color:#666; font-size:14px;">ทั้งหมด ${data.total} รายการ</p>`;
        data.chunks.forEach(chunk => {
            const div = document.createElement("div");
            div.className = "card";
            div.id = "kb-" + chunk.id;
            div.innerHTML = `
                <p style="color:#888; font-size:12px; margin-bottom:4px;">#${chunk.id}</p>
                <textarea id="kb-textarea-${chunk.id}" class="kb-textarea">${escapeHtml(chunk.content)}</textarea>
                <div style="margin-top:8px;">
                    <button onclick="saveKb(${chunk.id})">💾 บันทึก</button>
                    <button onclick="deleteKb(${chunk.id})">🗑️ ลบ</button>
                </div>
            `;
            container.appendChild(div);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลด Knowledge Base ไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

// ---------- เพิ่ม chunk เดี่ยว ----------
async function addSingleChunk() {
    const textarea = document.getElementById("newChunkText");
    const statusEl = document.getElementById("addChunkStatus");
    const content = textarea.value.trim();

    if (!content) {
        statusEl.textContent = "พิมพ์เนื้อหาก่อนกดเพิ่ม";
        statusEl.style.color = "red";
        return;
    }

    statusEl.textContent = "กำลังเพิ่ม...";
    statusEl.style.color = "#666";

    try {
        const res = await fetch("/admin/api/kb", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content })
        });
        if (!res.ok) throw new Error("HTTP " + res.status);

        textarea.value = "";
        statusEl.textContent = "✅ เพิ่มแล้ว";
        statusEl.style.color = "green";
        loadKb(1); // chunk ใหม่ id สูงสุด ไปโผล่หน้าสุดท้ายปกติ แต่กลับไปหน้า 1 ให้เห็นผลชัดเจนว่าเพิ่มสำเร็จ
    } catch (error) {
        statusEl.textContent = "❌ เพิ่มไม่สำเร็จ: " + error;
        statusEl.style.color = "red";
    }
}

// ---------- Import หลาย chunk จากไฟล์ ----------
async function bulkImportChunks() {
    const fileInput = document.getElementById("bulkFileInput");
    const statusEl = document.getElementById("bulkImportStatus");

    if (!fileInput.files || fileInput.files.length === 0) {
        statusEl.textContent = "เลือกไฟล์ก่อน";
        statusEl.style.color = "red";
        return;
    }

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    statusEl.textContent = "กำลัง import... (อาจใช้เวลาสักครู่ถ้าไฟล์ใหญ่)";
    statusEl.style.color = "#666";

    try {
        const res = await fetch("/admin/api/kb/bulk", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        fileInput.value = "";
        statusEl.textContent = `✅ import สำเร็จ ${data.count} chunk`;
        statusEl.style.color = "green";
        loadKb(1);
    } catch (error) {
        statusEl.textContent = "❌ import ไม่สำเร็จ: " + error;
        statusEl.style.color = "red";
    }
}

async function saveKb(id) {
    const textarea = document.getElementById("kb-textarea-" + id);
    const newContent = textarea.value;
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = "กำลังบันทึก...";

    try {
        const res = await fetch("/admin/api/kb/" + id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: newContent })
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        btn.textContent = "✅ บันทึกแล้ว";
        setTimeout(() => { btn.textContent = "💾 บันทึก"; btn.disabled = false; }, 1200);
    } catch (error) {
        alert("บันทึกไม่สำเร็จ: " + error);
        btn.textContent = "💾 บันทึก";
        btn.disabled = false;
    }
}

async function deleteKb(id) {
    if (!confirm("ยืนยันลบรายการนี้ออกจาก Knowledge Base ถาวร?")) return;

    removeCardOptimistically("kb-" + id);
    try {
        const res = await fetch("/admin/api/kb/" + id, { method: "DELETE" });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("ลบไม่สำเร็จ: " + error + " — กำลังโหลดรายการใหม่");
    } finally {
        loadKb(kbPage); // อยู่หน้าเดิม (ถ้าหน้านี้ว่างเปล่าไปหลังลบ ผู้ใช้กด "ก่อนหน้า" เองได้)
    }
}

// ---------- แท็บ 3: คำขอสมัครสมาชิก ----------
async function loadUserRequests(page = 1) {
    userRequestsPage = page;
    const container = document.getElementById("userRequestsContainer");
    try {
        const response = await fetch(`/admin/api/user-requests?page=${page}&page_size=${userRequestsPageSize}`);
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();

        renderPagination("userRequestsPagination", data.total, page, userRequestsPageSize,
            (newPage) => loadUserRequests(newPage),
            (newSize) => { userRequestsPageSize = newSize; loadUserRequests(1); });

        if (data.requests.length === 0) {
            container.innerHTML = page === 1
                ? "<p>ไม่มีคำขอสมัครสมาชิกรอตรวจสอบ 🎉</p>"
                : "<p>ไม่มีรายการในหน้านี้</p>";
            return;
        }

        container.innerHTML = "";
        data.requests.forEach(req => {
            const roleOptions = [1, 2, 3].map(r =>
                `<option value="${r}" ${r === req.requested_role ? "selected" : ""}>${ROLE_LABELS[r]}</option>`
            ).join("");

            const div = document.createElement("div");
            div.className = "card";
            div.id = "userreq-" + req.id;
            div.innerHTML = `
                <p><strong>ชื่อผู้ใช้:</strong> ${escapeHtml(req.username)}</p>
                <p><strong>ชื่อเล่น:</strong> ${escapeHtml(req.nickname || "-")}</p>
                <p><strong>ขอสิทธิ์ระดับ:</strong> ${ROLE_LABELS[req.requested_role] || req.requested_role}</p>
                <p style="color:#888; font-size:12px;">สมัครเมื่อ: ${req.created_at ? new Date(req.created_at).toLocaleString("th-TH") : "-"}</p>
                <div style="margin-top:8px;">
                    <label style="font-size:13px;">อนุมัติให้สิทธิ์ระดับ:
                        <select id="grant-role-${req.id}">${roleOptions}</select>
                    </label>
                </div>
                <div style="margin-top:8px;">
                    <button onclick="approveUserRequest(${req.id})">✅ อนุมัติ</button>
                    <button onclick="rejectUserRequest(${req.id})">❌ ปฏิเสธ</button>
                </div>
            `;
            container.appendChild(div);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลดรายการไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

async function approveUserRequest(userId) {
    const select = document.getElementById("grant-role-" + userId);
    const grantedRole = parseInt(select.value, 10);

    removeCardOptimistically("userreq-" + userId);
    try {
        const res = await fetch(`/admin/api/user-requests/${userId}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ granted_role: grantedRole })
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("อนุมัติไม่สำเร็จ: " + error + " — กำลังโหลดรายการใหม่");
    } finally {
        loadUserRequests(userRequestsPage);
    }
}

async function rejectUserRequest(userId) {
    removeCardOptimistically("userreq-" + userId);
    try {
        const res = await fetch(`/admin/api/user-requests/${userId}/reject`, { method: "POST" });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("ปฏิเสธไม่สำเร็จ: " + error + " — กำลังโหลดรายการใหม่");
    } finally {
        loadUserRequests(userRequestsPage);
    }
}

// ---------- แท็บ 4: จัดการบัญชีที่อนุมัติแล้ว ----------
async function loadUsers(page = 1) {
    usersPage = page;
    const container = document.getElementById("usersContainer");
    try {
        const response = await fetch(`/admin/api/users?page=${page}&page_size=${usersPageSize}`);
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();

        renderPagination("usersPagination", data.total, page, usersPageSize,
            (newPage) => loadUsers(newPage),
            (newSize) => { usersPageSize = newSize; loadUsers(1); });

        if (data.users.length === 0) {
            container.innerHTML = page === 1
                ? "<p>ยังไม่มีบัญชีที่อนุมัติแล้ว</p>"
                : "<p>ไม่มีรายการในหน้านี้</p>";
            return;
        }

        container.innerHTML = `<p style="color:#666; font-size:14px;">ทั้งหมด ${data.total} บัญชี</p>`;
        data.users.forEach(u => {
            const roleOptions = [1, 2, 3].map(r =>
                `<option value="${r}" ${r === u.role ? "selected" : ""}>${ROLE_LABELS[r]}</option>`
            ).join("");

            const div = document.createElement("div");
            div.className = "card";
            div.id = "user-" + u.id;
            div.innerHTML = `
                <p><strong>ชื่อผู้ใช้:</strong> ${escapeHtml(u.username)}</p>
                <p><strong>ชื่อเล่น:</strong> ${escapeHtml(u.nickname || "-")}</p>
                <p style="color:#888; font-size:12px;">สมัครเมื่อ: ${u.created_at ? new Date(u.created_at).toLocaleString("th-TH") : "-"}</p>
                <div style="margin-top:8px;">
                    <label style="font-size:13px;">สิทธิ์ปัจจุบัน:
                        <select id="user-role-${u.id}">${roleOptions}</select>
                    </label>
                    <button onclick="saveUserRole(${u.id})">💾 บันทึก</button>
                </div>
            `;
            container.appendChild(div);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลดรายการไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

async function saveUserRole(userId) {
    const select = document.getElementById("user-role-" + userId);
    const role = parseInt(select.value, 10);
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = "กำลังบันทึก...";

    try {
        const res = await fetch(`/admin/api/users/${userId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ role })
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        btn.textContent = "✅ บันทึกแล้ว";
        setTimeout(() => { btn.textContent = "💾 บันทึก"; btn.disabled = false; }, 1200);
    } catch (error) {
        alert("บันทึกไม่สำเร็จ: " + error);
        btn.textContent = "💾 บันทึก";
        btn.disabled = false;
    }
}

// ---------- Pagination UI (ใช้ร่วมกันทุกแท็บ) ----------
function renderPagination(containerId, total, currentPage, pageSize, onPageChange, onPageSizeChange) {
    const el = document.getElementById(containerId);
    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    if (total === 0) {
        el.innerHTML = "";
        return;
    }

    const sizeOptions = PAGE_SIZE_OPTIONS.map(size =>
        `<option value="${size}" ${size === pageSize ? "selected" : ""}>${size} รายการ/หน้า</option>`
    ).join("");

    el.innerHTML = `
        <div class="pagination-controls">
            <span class="pagination-info">ทั้งหมด ${total} รายการ — หน้า ${currentPage}/${totalPages}</span>
            <div class="pagination-buttons">
                <button ${currentPage <= 1 ? "disabled" : ""} id="${containerId}-prev">← ก่อนหน้า</button>
                <button ${currentPage >= totalPages ? "disabled" : ""} id="${containerId}-next">ถัดไป →</button>
                <select id="${containerId}-size">${sizeOptions}</select>
            </div>
        </div>
    `;

    document.getElementById(containerId + "-prev").onclick = () => {
        if (currentPage > 1) onPageChange(currentPage - 1);
    };
    document.getElementById(containerId + "-next").onclick = () => {
        if (currentPage < totalPages) onPageChange(currentPage + 1);
    };
    document.getElementById(containerId + "-size").onchange = (e) => {
        onPageSizeChange(parseInt(e.target.value, 10));
    };
}

// ---------- Helpers ----------
function removeCardOptimistically(elementId) {
    const el = document.getElementById(elementId);
    if (el) el.remove();
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ---------- Init ----------
loadLogs(1); // แท็บเริ่มต้นคือ "รอตรวจสอบ"
