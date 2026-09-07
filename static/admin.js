// ---------- Tab switching ----------
let currentTab = "pending"; // จำแท็บที่เปิดอยู่ตลอด session ของหน้า (ไม่ผูกกับ URL เพราะไม่ reload หน้า)

// ---------- Pagination state (แยกกันคนละแท็บ) ----------
let pendingPage = 1;
let pendingPageSize = 10;

let kbPage = 1;
let kbPageSize = 10;
let kbSelectedTagIds = new Set(); // เก็บ tag id ที่กำลังกรองอยู่ (เลือกได้หลายอัน พร้อมกัน = OR)

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
    document.getElementById("tabTags").style.display = tab === "tags" ? "block" : "none";

    document.getElementById("tabBtnPending").classList.toggle("tab-btn-active", tab === "pending");
    document.getElementById("tabBtnKb").classList.toggle("tab-btn-active", tab === "kb");
    document.getElementById("tabBtnUserRequests").classList.toggle("tab-btn-active", tab === "userRequests");
    document.getElementById("tabBtnUsers").classList.toggle("tab-btn-active", tab === "users");
    document.getElementById("tabBtnTags").classList.toggle("tab-btn-active", tab === "tags");

    if (tab === "pending") {
        loadLogs(pendingPage);
    } else if (tab === "kb") {
        loadKb(kbPage);
        loadKbTagFilterList();
    } else if (tab === "userRequests") {
        loadUserRequests(userRequestsPage);
    } else if (tab === "users") {
        loadUsers(usersPage);
    } else if (tab === "tags") {
        loadTagManagerList();
        loadIdRangeHint();
        loadScopeTagList();
        updateScopePreview();
        loadSnapshotList();
        loadAgentProposals();
        loadAgentJobList();
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
        const tagIdsParam = kbSelectedTagIds.size > 0 ? Array.from(kbSelectedTagIds).join(",") : "";
        const response = await fetch(`/admin/api/kb?page=${page}&page_size=${kbPageSize}&tag_ids=${tagIdsParam}`);
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();

        renderPagination("kbPagination", data.total, page, kbPageSize, (newPage) => loadKb(newPage), (newSize) => {
            kbPageSize = newSize;
            loadKb(1);
        });

        if (data.chunks.length === 0) {
            container.innerHTML = page === 1
                ? "<p>ไม่มีข้อมูลตรงกับตัวกรองนี้</p>"
                : "<p>ไม่มีรายการในหน้านี้</p>";
            return;
        }

        container.innerHTML = `<p style="color:#666; font-size:14px;">ทั้งหมด ${data.total} รายการ</p>`;
        data.chunks.forEach(chunk => {
            const div = document.createElement("div");
            div.className = "card";
            div.id = "kb-" + chunk.id;
            const tagsValue = (chunk.tags || []).join(", ");
            const tagBadges = (chunk.tags || []).map(t => `<span class="kb-tag-badge">${escapeHtml(t)}</span>`).join(" ");
            div.innerHTML = `
                <p style="color:#888; font-size:12px; margin-bottom:4px;">#${chunk.id} ${tagBadges}</p>
                <textarea id="kb-textarea-${chunk.id}" class="kb-textarea">${escapeHtml(chunk.content)}</textarea>
                <input type="text" id="kb-tags-${chunk.id}" class="kb-tag-input" value="${escapeHtml(tagsValue)}" placeholder="Tag (คั่นด้วย ,)">
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

// ---------- ตัวกรอง tag ----------
async function loadKbTagFilterList() {
    const listEl = document.getElementById("kbTagFilterList");
    try {
        const res = await fetch("/admin/api/tags");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        if (data.tags.length === 0) {
            listEl.innerHTML = '<span class="kb-filter-empty">ยังไม่มี tag ในระบบ</span>';
            return;
        }

        listEl.innerHTML = "";
        data.tags.forEach(tag => {
            const chip = document.createElement("span");
            chip.className = "kb-tag-filter-chip" + (kbSelectedTagIds.has(tag.id) ? " active" : "");
            chip.textContent = `${tag.name} (${tag.count})`;
            chip.onclick = () => toggleKbTagFilter(tag.id);
            listEl.appendChild(chip);
        });
    } catch (error) {
        listEl.innerHTML = '<span class="kb-filter-empty">โหลด tag ไม่สำเร็จ</span>';
    }
}

function toggleKbTagFilter(tagId) {
    if (kbSelectedTagIds.has(tagId)) {
        kbSelectedTagIds.delete(tagId);
    } else {
        kbSelectedTagIds.add(tagId);
    }
    loadKbTagFilterList(); // อัปเดต highlight chip ที่เลือกอยู่
    loadKb(1); // กรองใหม่ กลับไปหน้า 1 เสมอ
}

function clearKbTagFilter() {
    kbSelectedTagIds.clear();
    loadKbTagFilterList();
    loadKb(1);
}

function exportKb() {
    const tagIdsParam = kbSelectedTagIds.size > 0 ? Array.from(kbSelectedTagIds).join(",") : "";
    // เปิด URL ตรงๆ ให้ browser จัดการดาวน์โหลดเอง (endpoint ส่ง Content-Disposition: attachment มาแล้ว)
    window.location.href = `/admin/api/kb/export?tag_ids=${tagIdsParam}`;
}

// ---------- เพิ่ม chunk เดี่ยว ----------
async function addSingleChunk() {
    const textarea = document.getElementById("newChunkText");
    const tagsInput = document.getElementById("newChunkTags");
    const idInput = document.getElementById("newChunkId");
    const statusEl = document.getElementById("addChunkStatus");
    const content = textarea.value.trim();

    if (!content) {
        statusEl.textContent = "พิมพ์เนื้อหาก่อนกดเพิ่ม";
        statusEl.style.color = "red";
        return;
    }

    const tags = tagsInput.value.split(",").map(t => t.trim()).filter(t => t);
    const idValue = idInput.value.trim();
    const chunkId = idValue ? parseInt(idValue, 10) : null;

    statusEl.textContent = "กำลังเพิ่ม...";
    statusEl.style.color = "#666";

    try {
        const res = await fetch("/admin/api/kb", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content, tags, chunk_id: chunkId })
        });
        const data = await res.json();

        if (res.status === 409) {
            // id ที่ระบุชนกับ chunk ที่มีอยู่แล้ว — popup เตือนชัดเจนแยกจาก error ทั่วไป
            alert("⚠️ " + data.detail);
            statusEl.textContent = "";
            return;
        }
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        textarea.value = "";
        tagsInput.value = "";
        idInput.value = "";
        statusEl.textContent = `✅ เพิ่มแล้ว (#${data.id})`;
        statusEl.style.color = "green";
        loadKb(1); // chunk ใหม่ id สูงสุด ไปโผล่หน้าสุดท้ายปกติ แต่กลับไปหน้า 1 ให้เห็นผลชัดเจนว่าเพิ่มสำเร็จ
        loadKbTagFilterList(); // เผื่อมี tag ใหม่เกิดขึ้น ให้ขึ้นในตัวกรองด้วย
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
    const tagsInput = document.getElementById("kb-tags-" + id);
    const newContent = textarea.value;
    const tags = tagsInput.value.split(",").map(t => t.trim()).filter(t => t);
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = "กำลังบันทึก...";

    try {
        const res = await fetch("/admin/api/kb/" + id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: newContent, tags })
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        btn.textContent = "✅ บันทึกแล้ว";
        setTimeout(() => {
            btn.textContent = "💾 บันทึก";
            btn.disabled = false;
            loadKbTagFilterList(); // เผื่อมี tag ใหม่/เปลี่ยนจำนวน ให้ตัวกรองอัปเดตตาม
        }, 1200);
    } catch (error) {
        alert("บันทึกไม่สำเร็จ: " + error);
        btn.textContent = "💾 บันทึก";
        btn.disabled = false;
    }
}

async function deleteKb(id) {
    // โชว์เนื้อหาจริงในข้อความเตือน ไม่ใช่แค่ "ยืนยันลบ?" เฉยๆ — กันอุบัติเหตุกดลบผิดตัวโดยไม่ทันเห็นว่าลบอะไรไป
    const textarea = document.getElementById("kb-textarea-" + id);
    const fullText = textarea ? textarea.value : "";
    const preview = fullText.slice(0, 150) + (fullText.length > 150 ? "..." : "");

    const confirmed = confirm(
        `⚠️ ยืนยันลบ chunk #${id} นี้ออกจาก Knowledge Base ถาวร?\n\n` +
        `เนื้อหา: "${preview}"\n\n` +
        `การกระทำนี้ย้อนกลับไม่ได้ทันที (กู้คืนได้เฉพาะจาก backup เท่านั้น)`
    );
    if (!confirmed) return;

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

            const isBlocked = u.status === "blocked";
            const statusBadge = isBlocked
                ? `<span class="status-badge status-badge-blocked">🚫 ถูกระงับ</span>`
                : `<span class="status-badge status-badge-active">✅ ใช้งานได้ปกติ</span>`;
            const blockButtonHtml = isBlocked
                ? `<button onclick="unblockUser(${u.id})">🔓 ปลดระงับ</button>`
                : `<button onclick="blockUser(${u.id})">🔒 ระงับการใช้งาน</button>`;

            const div = document.createElement("div");
            div.className = "card";
            div.id = "user-" + u.id;
            div.innerHTML = `
                <p><strong>ชื่อผู้ใช้:</strong> ${escapeHtml(u.username)} ${statusBadge}</p>
                <p><strong>ชื่อเล่น:</strong> ${escapeHtml(u.nickname || "-")}</p>
                <p style="color:#888; font-size:12px;">สมัครเมื่อ: ${u.created_at ? new Date(u.created_at).toLocaleString("th-TH") : "-"}</p>
                <div style="margin-top:8px;">
                    <label style="font-size:13px;">สิทธิ์ปัจจุบัน:
                        <select id="user-role-${u.id}">${roleOptions}</select>
                    </label>
                    <button onclick="saveUserRole(${u.id})">💾 บันทึก</button>
                </div>
                <div style="margin-top:8px;">
                    ${blockButtonHtml}
                    <button onclick="deleteUser(${u.id})" class="danger-btn">🗑️ ลบบัญชี</button>
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

async function blockUser(userId) {
    if (!confirm("ระงับการใช้งานบัญชีนี้? ผู้ใช้จะถูกบังคับ logout จากทุกอุปกรณ์ทันที")) return;
    try {
        const res = await fetch(`/admin/api/users/${userId}/block`, { method: "POST" });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("ระงับการใช้งานไม่สำเร็จ: " + error);
    } finally {
        loadUsers(usersPage);
    }
}

async function unblockUser(userId) {
    try {
        const res = await fetch(`/admin/api/users/${userId}/unblock`, { method: "POST" });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("ปลดระงับไม่สำเร็จ: " + error);
    } finally {
        loadUsers(usersPage);
    }
}

async function deleteUser(userId) {
    if (!confirm("ลบบัญชีนี้ถาวร? ข้อมูลทั้งหมด (ประวัติแชท คำถามกันลืมรหัสผ่าน) จะหายและกู้คืนไม่ได้")) return;

    removeCardOptimistically("user-" + userId);
    try {
        const res = await fetch(`/admin/api/users/${userId}`, { method: "DELETE" });
        if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (error) {
        alert("ลบไม่สำเร็จ: " + error + " — กำลังโหลดรายการใหม่");
    } finally {
        loadUsers(usersPage);
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

// ---------- แท็บ 5: จัดการ Tag ----------
async function loadTagManagerList() {
    const container = document.getElementById("tagManagerList");
    try {
        const res = await fetch("/admin/api/tags");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        if (data.tags.length === 0) {
            container.innerHTML = "<p>ยังไม่มี tag ในระบบ — เพิ่มได้จากแท็บ Knowledge Base หรือช่องด้านล่าง</p>";
            return;
        }

        container.innerHTML = "";
        data.tags.forEach(tag => {
            const row = document.createElement("div");
            row.className = "tag-manager-row";
            row.id = "tag-row-" + tag.id;
            row.innerHTML = `
                <input type="text" id="tag-name-${tag.id}" value="${escapeHtml(tag.name)}" class="kb-tag-input">
                <span class="tag-count-label">${tag.count} chunk</span>
                <button onclick="saveTagRename(${tag.id})">💾 บันทึกชื่อ</button>
                <button onclick="deleteTagEntirely(${tag.id})" class="danger-btn">🗑️ ลบทั้งหมด</button>
            `;
            container.appendChild(row);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลด tag ไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

async function saveTagRename(tagId) {
    const input = document.getElementById("tag-name-" + tagId);
    const newName = input.value.trim();
    if (!newName) {
        alert("ชื่อ tag ห้ามว่างเปล่า");
        return;
    }

    try {
        const res = await fetch(`/admin/api/tags/${tagId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        loadTagManagerList();
        loadKbTagFilterList(); // sync กับตัวกรองในแท็บ KB ด้วย
        loadScopeTagList();    // sync กับ scope filter ในแท็บนี้ด้วย
    } catch (error) {
        alert("เปลี่ยนชื่อไม่สำเร็จ: " + error);
    }
}

async function deleteTagEntirely(tagId) {
    if (!confirm("ลบ tag นี้ออกจากทุก chunk ทั้งหมดในระบบถาวร? (ตัว chunk เองไม่หาย แค่ tag นี้จะหายไปจากทุกที่)")) return;

    try {
        const res = await fetch(`/admin/api/tags/${tagId}`, { method: "DELETE" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        loadTagManagerList();
        loadKbTagFilterList();
        loadScopeTagList();
    } catch (error) {
        alert("ลบไม่สำเร็จ: " + error);
    }
}

async function loadIdRangeHint() {
    const hintEl = document.getElementById("idRangeHint");
    try {
        const res = await fetch("/admin/api/kb/id-range");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        if (data.min_id === null) {
            hintEl.textContent = "Knowledge Base ยังว่างเปล่า ไม่มี id ให้ระบุช่วง";
        } else {
            hintEl.textContent = `ช่วง ID ปัจจุบันใน Knowledge Base: ${data.min_id} ถึง ${data.max_id}`;
        }
    } catch (error) {
        hintEl.textContent = "เช็คช่วง id ไม่สำเร็จ";
    }
}

async function addTagToRange() {
    const tagName = document.getElementById("rangeAddTagName").value.trim();
    const startId = parseInt(document.getElementById("rangeAddStart").value, 10);
    const endId = parseInt(document.getElementById("rangeAddEnd").value, 10);
    const statusEl = document.getElementById("rangeAddStatus");

    if (!tagName || isNaN(startId) || isNaN(endId)) {
        statusEl.textContent = "กรอกชื่อ tag และช่วง ID ให้ครบ";
        statusEl.style.color = "red";
        return;
    }
    if (startId > endId) {
        statusEl.textContent = "ID เริ่มต้องน้อยกว่าหรือเท่ากับ ID สิ้นสุด";
        statusEl.style.color = "red";
        return;
    }

    statusEl.textContent = "กำลังเพิ่ม...";
    statusEl.style.color = "#666";

    try {
        const res = await fetch("/admin/api/tags/add-range", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tag_name: tagName, start_id: startId, end_id: endId })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        statusEl.textContent = `✅ เพิ่ม tag "${tagName}" ให้ ${data.count} chunk แล้ว`;
        statusEl.style.color = "green";
        loadTagManagerList();
        loadKbTagFilterList();
        loadScopeTagList();
    } catch (error) {
        statusEl.textContent = "❌ ไม่สำเร็จ: " + error;
        statusEl.style.color = "red";
    }
}

async function removeTagFromRange() {
    const tagId = document.getElementById("rangeRemoveTagId").value;
    const startId = parseInt(document.getElementById("rangeRemoveStart").value, 10);
    const endId = parseInt(document.getElementById("rangeRemoveEnd").value, 10);
    const statusEl = document.getElementById("rangeRemoveStatus");

    if (!tagId || isNaN(startId) || isNaN(endId)) {
        statusEl.textContent = "เลือก tag และกรอกช่วง ID ให้ครบ";
        statusEl.style.color = "red";
        return;
    }
    if (startId > endId) {
        statusEl.textContent = "ID เริ่มต้องน้อยกว่าหรือเท่ากับ ID สิ้นสุด";
        statusEl.style.color = "red";
        return;
    }

    statusEl.textContent = "กำลังลบ...";
    statusEl.style.color = "#666";

    try {
        const res = await fetch(`/admin/api/tags/${tagId}/remove-range`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start_id: startId, end_id: endId })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        statusEl.textContent = `✅ ลบ tag ออกจาก ${data.count} chunk แล้ว`;
        statusEl.style.color = "green";
        loadTagManagerList();
        loadKbTagFilterList();
        loadScopeTagList();
    } catch (error) {
        statusEl.textContent = "❌ ไม่สำเร็จ: " + error;
        statusEl.style.color = "red";
    }
}

// เติม dropdown เลือก tag สำหรับ "ลบ tag ออกจากช่วง ID" ให้ตรงกับ tag ที่มีจริงในระบบ
async function loadRangeRemoveDropdown() {
    try {
        const res = await fetch("/admin/api/tags");
        const data = await res.json();
        const select = document.getElementById("rangeRemoveTagId");
        select.innerHTML = '<option value="">เลือก tag...</option>' +
            data.tags.map(t => `<option value="${t.id}">${escapeHtml(t.name)} (${t.count})</option>`).join("");
    } catch (error) {
        // เงียบไว้ ไม่ critical ถ้าโหลด dropdown นี้พลาด — ผู้ใช้ยังกดปุ่มอื่นในแท็บนี้ได้ปกติ
    }
}

// ---------- Scope filter (เตรียมไว้สำหรับ AI Agent ในระยะถัดไป — ตอนนี้ใช้ preview จำนวนก่อน) ----------
let scopeSelectedTagIds = new Set();

async function loadScopeTagList() {
    const listEl = document.getElementById("scopeTagList");
    try {
        const res = await fetch("/admin/api/tags");
        const data = await res.json();

        if (data.tags.length === 0) {
            listEl.innerHTML = '<span class="kb-filter-empty">ยังไม่มี tag ในระบบ</span>';
            return;
        }

        listEl.innerHTML = "";
        data.tags.forEach(tag => {
            const chip = document.createElement("span");
            chip.className = "kb-tag-filter-chip" + (scopeSelectedTagIds.has(tag.id) ? " active" : "");
            chip.textContent = `${tag.name} (${tag.count})`;
            chip.onclick = () => {
                if (scopeSelectedTagIds.has(tag.id)) {
                    scopeSelectedTagIds.delete(tag.id);
                } else {
                    scopeSelectedTagIds.add(tag.id);
                }
                loadScopeTagList();
                updateScopePreview();
            };
            listEl.appendChild(chip);
        });
    } catch (error) {
        listEl.innerHTML = '<span class="kb-filter-empty">โหลด tag ไม่สำเร็จ</span>';
    }

    loadRangeRemoveDropdown(); // โหลดคู่กันไปเลย ใช้ endpoint เดียวกัน
}

function onScopeModeChange() {
    const mode = document.querySelector('input[name="scopeMode"]:checked').value;

    // ซ่อนตัวเลือกย่อยทั้งหมดก่อน แล้วค่อยโชว์เฉพาะอันที่ตรงกับโหมดที่เลือก
    // (ใช้ radio button ตั้งแต่แรกเพราะ radio "เลือกได้ทีละอัน" อยู่แล้วในตัว
    // ตรงกับที่ขอว่า "เลือกทั้งหมดแล้วต้อง uncheck อย่างอื่นที่ขัดกัน" โดยไม่ต้องเขียน logic เพิ่ม)
    document.getElementById("scopeTagList").style.display = mode === "tags" ? "flex" : "none";
    document.getElementById("scopeIdRangeRow").style.display = mode === "id_range" ? "flex" : "none";

    updateScopePreview();
}

async function updateScopePreview() {
    const mode = document.querySelector('input[name="scopeMode"]:checked').value;
    const countEl = document.getElementById("scopePreviewCount");
    countEl.textContent = "...";

    let url = "/admin/api/kb/scope-count?";
    if (mode === "tags") {
        if (scopeSelectedTagIds.size === 0) {
            countEl.textContent = "0";
            return;
        }
        url += "tag_ids=" + Array.from(scopeSelectedTagIds).join(",");
    } else if (mode === "id_range") {
        const startId = document.getElementById("scopeStartId").value;
        const endId = document.getElementById("scopeEndId").value;
        if (!startId || !endId) {
            countEl.textContent = "-";
            return;
        }
        url += `start_id=${startId}&end_id=${endId}`;
    } else if (mode === "untagged") {
        url += "untagged=true";
    }
    // mode === "all" ไม่ต้องเติม query อะไรเลย นับทั้งหมด

    try {
        const res = await fetch(url);
        const data = await res.json();
        countEl.textContent = data.count;
    } catch (error) {
        countEl.textContent = "เช็คไม่สำเร็จ";
    }
}

// ---------- Backup / Rollback ----------
async function loadSnapshotList() {
    const container = document.getElementById("snapshotList");
    try {
        const res = await fetch("/admin/api/kb/snapshots");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        if (data.snapshots.length === 0) {
            container.innerHTML = "<p>ยังไม่มี backup เลย — กด \"สร้าง Backup ตอนนี้\" ด้านบนเพื่อเริ่มต้น</p>";
            return;
        }

        container.innerHTML = "";
        data.snapshots.forEach(snap => {
            const row = document.createElement("div");
            row.className = "snapshot-row";
            const dateStr = snap.created_at ? new Date(snap.created_at).toLocaleString("th-TH") : "-";
            row.innerHTML = `
                <div class="snapshot-info">
                    <strong>#${snap.id}</strong> — ${dateStr}<br>
                    <span class="snapshot-meta">${escapeHtml(snap.label || "(ไม่มีป้ายกำกับ)")} · ${snap.chunk_count} chunk</span>
                </div>
                <button onclick="rollbackToSnapshot(${snap.id})" class="danger-btn">⏮️ Rollback ไปเวอร์ชันนี้</button>
            `;
            container.appendChild(row);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลดรายการ backup ไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

async function createKbSnapshot() {
    const statusEl = document.getElementById("snapshotCreateStatus");
    const label = prompt("ใส่ป้ายกำกับ backup นี้ (ไม่บังคับ เช่น 'ก่อนแก้หมวดภาษี')") || "";

    statusEl.textContent = "กำลังสร้าง backup...";
    statusEl.style.color = "#666";

    try {
        const res = await fetch("/admin/api/kb/snapshots", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        statusEl.textContent = `✅ สร้าง backup #${data.id} สำเร็จ`;
        statusEl.style.color = "green";
        loadSnapshotList();
    } catch (error) {
        statusEl.textContent = "❌ สร้าง backup ไม่สำเร็จ: " + error;
        statusEl.style.color = "red";
    }
}

async function rollbackToSnapshot(snapshotId) {
    const confirmed = confirm(
        `⚠️⚠️ ยืนยัน Rollback กลับไปเป็น backup #${snapshotId}?\n\n` +
        `การกระทำนี้จะ "ลบข้อมูล Knowledge Base ปัจจุบันทั้งหมดทิ้ง" แล้วแทนที่ด้วยข้อมูลใน backup นี้\n\n` +
        `ระบบจะสร้าง backup ของสถานะปัจจุบันไว้ให้อัตโนมัติก่อน rollback (เผื่อ rollback ผิดเวอร์ชันจะย้อนกลับมาได้อีกที) ` +
        `แต่ยืนยันก่อนว่าต้องการทำจริงๆ ใช่ไหม?`
    );
    if (!confirmed) return;

    try {
        const res = await fetch(`/admin/api/kb/snapshots/${snapshotId}/rollback`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        alert("✅ Rollback สำเร็จแล้ว");
        loadSnapshotList();
        loadTagManagerList();
        loadKbTagFilterList();
        loadScopeTagList();
    } catch (error) {
        alert("❌ Rollback ไม่สำเร็จ: " + error);
    }
}

// ---------- AI Agent (ระยะ 3) ----------
function onAgentActionChange() {
    const action = document.querySelector('input[name="agentAction"]:checked').value;
    document.getElementById("agentTagOptions").style.display = action === "suggest_tags" ? "block" : "none";
    document.getElementById("agentMergeOptions").style.display = action === "merge_chunks" ? "block" : "none";
}

// ดึง scope ปัจจุบันจากกล่อง "กำหนดขอบเขต" ด้านบน (ใช้ scopeSelectedTagIds ตัวเดียวกับที่มีอยู่แล้ว)
function getCurrentAgentScope() {
    const mode = document.querySelector('input[name="scopeMode"]:checked').value;
    const scope = { scope_mode: mode };
    if (mode === "tags") {
        scope.tag_ids = Array.from(scopeSelectedTagIds);
    } else if (mode === "id_range") {
        scope.start_id = parseInt(document.getElementById("scopeStartId").value, 10);
        scope.end_id = parseInt(document.getElementById("scopeEndId").value, 10);
    }
    return scope;
}

async function startAgentJob() {
    const actionType = document.querySelector('input[name="agentAction"]:checked').value;
    const agentMode = document.querySelector('input[name="agentMode"]:checked').value;
    const statusEl = document.getElementById("agentRunStatus");
    const scope = getCurrentAgentScope();

    if (scope.scope_mode === "tags" && (!scope.tag_ids || scope.tag_ids.length === 0)) {
        statusEl.textContent = "เลือก tag อย่างน้อย 1 อันในกล่อง 'กำหนดขอบเขต' ด้านบนก่อน";
        statusEl.style.color = "red";
        return;
    }
    if (scope.scope_mode === "id_range" && (isNaN(scope.start_id) || isNaN(scope.end_id))) {
        statusEl.textContent = "กรอกช่วง ID ในกล่อง 'กำหนดขอบเขต' ด้านบนให้ครบก่อน";
        statusEl.style.color = "red";
        return;
    }

    const confirmed = confirm(
        "⚠️⚠️⚠️ ก่อนเริ่มงานนี้ Agent จะแก้ไขข้อมูลใน Knowledge Base จริง\n\n" +
        "ระบบจะสร้าง Backup อัตโนมัติให้ก่อนเริ่มเสมอ (กด Rollback ย้อนกลับได้ทีหลังถ้าผลไม่ดี) " +
        "แต่แนะนำให้กด \"📸 สร้าง Backup ตอนนี้\" ด้วยตัวเองเพิ่มอีกชั้นก่อนเริ่ม เพื่อความปลอดภัยสูงสุด\n\n" +
        "ยืนยันเริ่มทำงานจริงหรือไม่?"
    );
    if (!confirmed) return;

    const body = { action_type: actionType, mode: agentMode, ...scope };
    if (actionType === "suggest_tags") {
        body.tag_strategy = document.querySelector('input[name="tagStrategy"]:checked').value;
    } else {
        body.merge_strategy = document.querySelector('input[name="mergeStrategy"]:checked').value;
    }

    statusEl.textContent = "กำลังทำงาน... (อาจใช้เวลาสักครู่ถึงหลายนาทีถ้า scope ใหญ่ กรุณาอย่าปิดหน้านี้)";
    statusEl.style.color = "#666";

    try {
        const res = await fetch("/admin/api/agent/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        if (data.status === "completed") {
            const count = data.applied_count !== undefined ? data.applied_count : data.merged_count;
            statusEl.textContent = `✅ ทำงานเสร็จสมบูรณ์ — ดำเนินการ ${count} รายการ (Job #${data.job_id})`;
            loadKb(1);
            loadTagManagerList();
            loadKbTagFilterList();
            loadScopeTagList();
        } else {
            statusEl.textContent = `✅ สร้างข้อเสนอ ${data.proposal_count} รายการ รอตรวจสอบด้านล่าง (Job #${data.job_id})`;
            loadAgentProposals();
        }
        statusEl.style.color = "green";
        loadAgentJobList();
    } catch (error) {
        statusEl.textContent = "❌ ทำงานไม่สำเร็จ: " + error;
        statusEl.style.color = "red";
        loadAgentJobList(); // แสดง job ที่ล้มเหลวในประวัติด้วย พร้อมปุ่ม rollback
    }
}

async function loadAgentProposals() {
    const container = document.getElementById("agentProposalList");
    try {
        const res = await fetch("/admin/api/agent/proposals");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        if (data.proposals.length === 0) {
            container.innerHTML = "<p>ไม่มีรายการรอตรวจสอบตอนนี้</p>";
            return;
        }

        container.innerHTML = "";
        data.proposals.forEach(p => {
            const div = document.createElement("div");
            div.className = "card";
            div.id = "proposal-" + p.id;

            if (p.proposal_type === "add_tags") {
                const tagsValue = (p.payload.suggested_tags || []).join(", ");
                div.innerHTML = `
                    <p><strong>เสนอเพิ่ม Tag ให้ chunk #${p.payload.chunk_id}</strong></p>
                    <input type="text" id="proposal-tags-${p.id}" class="kb-tag-input" value="${escapeHtml(tagsValue)}">
                    <div style="margin-top:8px;">
                        <button onclick="approveProposal(${p.id}, 'add_tags')">✅ ยืนยัน</button>
                        <button onclick="rejectProposal(${p.id})" class="danger-btn">❌ ปฏิเสธ</button>
                    </div>
                `;
            } else if (p.proposal_type === "merge") {
                const chunkIdsStr = (p.payload.chunk_ids || []).map(id => "#" + id).join(", ");
                div.innerHTML = `
                    <p><strong>เสนอยุบรวม chunk ${chunkIdsStr}</strong></p>
                    <p style="color:#888; font-size:12px;">เหตุผลจาก Agent: ${escapeHtml(p.payload.reason || "-")}</p>
                    <textarea id="proposal-content-${p.id}" class="kb-textarea">${escapeHtml(p.payload.merged_content || "")}</textarea>
                    <div style="margin-top:8px;">
                        <button onclick="approveProposal(${p.id}, 'merge')">✅ ยืนยัน (ลบของเดิม สร้างใหม่แทน)</button>
                        <button onclick="rejectProposal(${p.id})" class="danger-btn">❌ ปฏิเสธ</button>
                    </div>
                `;
            }
            container.appendChild(div);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลดรายการไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

async function approveProposal(proposalId, type) {
    const body = {};
    if (type === "add_tags") {
        const tagsInput = document.getElementById("proposal-tags-" + proposalId);
        body.edited_tags = tagsInput.value.split(",").map(t => t.trim()).filter(t => t);
    } else if (type === "merge") {
        const contentInput = document.getElementById("proposal-content-" + proposalId);
        body.edited_content = contentInput.value;
    }

    try {
        const res = await fetch(`/admin/api/agent/proposals/${proposalId}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));

        loadAgentProposals();
        loadKb(1);
        loadTagManagerList();
        loadKbTagFilterList();
        loadScopeTagList();
    } catch (error) {
        alert("ยืนยันไม่สำเร็จ: " + error);
    }
}

async function rejectProposal(proposalId) {
    try {
        const res = await fetch(`/admin/api/agent/proposals/${proposalId}/reject`, { method: "POST" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        loadAgentProposals();
    } catch (error) {
        alert("ปฏิเสธไม่สำเร็จ: " + error);
    }
}

async function loadAgentJobList() {
    const container = document.getElementById("agentJobList");
    try {
        const res = await fetch("/admin/api/agent/jobs");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        if (data.jobs.length === 0) {
            container.innerHTML = "<p>ยังไม่เคยรัน Agent เลย</p>";
            return;
        }

        const statusLabels = {
            running: "🔄 กำลังทำงาน", completed: "✅ เสร็จสมบูรณ์",
            awaiting_review: "📋 รอตรวจสอบ", failed: "❌ ล้มเหลว",
        };

        container.innerHTML = "";
        data.jobs.forEach(job => {
            const row = document.createElement("div");
            row.className = "snapshot-row";
            const dateStr = job.created_at ? new Date(job.created_at).toLocaleString("th-TH") : "-";
            const statusLabel = statusLabels[job.status] || job.status;
            const rollbackBtn = job.pre_snapshot_id
                ? `<button onclick="rollbackToSnapshot(${job.pre_snapshot_id})" class="danger-btn">⏮️ Rollback ไปก่อนงานนี้</button>`
                : "";
            row.innerHTML = `
                <div class="snapshot-info">
                    <strong>#${job.id}</strong> — ${dateStr}<br>
                    <span class="snapshot-meta">${escapeHtml(job.action_type)} · ${escapeHtml(job.mode)} · scope: ${escapeHtml(job.scope_summary || '-')} · ${statusLabel}</span>
                </div>
                ${rollbackBtn}
            `;
            container.appendChild(row);
        });
    } catch (error) {
        container.innerHTML = "<p style='color:red;'>โหลดประวัติไม่สำเร็จ: " + escapeHtml(String(error)) + "</p>";
    }
}

// ---------- Init ----------
loadLogs(1); // แท็บเริ่มต้นคือ "รอตรวจสอบ"
