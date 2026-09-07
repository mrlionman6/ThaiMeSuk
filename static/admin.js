<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin - จัดการ Knowledge Base</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <h1>🔧 Admin: จัดการระบบ
        <a href="/admin/logout" style="font-size:14px; float:right;">🚪 Logout</a>
    </h1>

    <div class="tab-bar">
        <button id="tabBtnPending" class="tab-btn tab-btn-active" onclick="switchTab('pending')">
            📋 รอตรวจสอบ
        </button>
        <button id="tabBtnKb" class="tab-btn" onclick="switchTab('kb')">
            📚 Knowledge Base
        </button>
        <button id="tabBtnUserRequests" class="tab-btn" onclick="switchTab('userRequests')">
            🙋 คำขอสมัครสมาชิก
        </button>
        <button id="tabBtnUsers" class="tab-btn" onclick="switchTab('users')">
            👥 จัดการบัญชี
        </button>
        <button id="tabBtnTags" class="tab-btn" onclick="switchTab('tags')">
            🏷️ จัดการ Tag
        </button>
    </div>

    <div id="tabPending" class="tab-panel">
        <div id="logsContainer">กำลังโหลด...</div>
        <div id="logsPagination" class="pagination-bar"></div>
    </div>

    <div id="tabKb" class="tab-panel" style="display:none;">
        <div class="kb-toolbar">
            <details class="kb-toolbar-section">
                <summary>➕ เพิ่ม chunk เดี่ยว</summary>
                <div class="kb-toolbar-body">
                    <textarea id="newChunkText" class="kb-textarea" placeholder="พิมพ์เนื้อหาที่จะเพิ่มเข้า Knowledge Base"></textarea>
                    <input type="text" id="newChunkTags" class="kb-tag-input" placeholder="Tag (คั่นด้วย , เช่น ภาษี, ที่ดิน) — ไม่บังคับ">
                    <input type="number" id="newChunkId" class="kb-tag-input" placeholder="ID ตำแหน่งที่ต้องการ (ไม่กรอก = ต่อท้ายอัตโนมัติ)">
                    <button onclick="addSingleChunk()">เพิ่ม</button>
                    <span id="addChunkStatus" class="kb-toolbar-status"></span>
                </div>
            </details>
            <details class="kb-toolbar-section">
                <summary>📁 Import จากไฟล์ (หลาย chunk พร้อมกัน)</summary>
                <div class="kb-toolbar-body">
                    <p class="ts-note">รองรับ .json (list ของข้อความ หรือ dict {"content":"...","tags":["ภาษี"]} ถ้าอยากใส่ tag มาด้วย) หรือ .txt (หนึ่งบรรทัดต่อหนึ่ง chunk ไม่มี tag)</p>
                    <input type="file" id="bulkFileInput" accept=".json,.txt">
                    <button onclick="bulkImportChunks()">Import</button>
                    <span id="bulkImportStatus" class="kb-toolbar-status"></span>
                </div>
            </details>
        </div>

        <div class="kb-filter-bar">
            <label class="kb-filter-label">กรองตาม tag:</label>
            <div id="kbTagFilterList" class="kb-tag-filter-list">กำลังโหลด tag...</div>
            <button type="button" onclick="clearKbTagFilter()" class="kb-filter-clear-btn">ล้างตัวกรอง</button>
            <button type="button" onclick="exportKb()" class="kb-export-btn">📤 Export</button>
        </div>

        <div id="kbContainer">กำลังโหลด...</div>
        <div id="kbPagination" class="pagination-bar"></div>
    </div>

    <div id="tabUserRequests" class="tab-panel" style="display:none;">
        <div id="userRequestsContainer">กำลังโหลด...</div>
        <div id="userRequestsPagination" class="pagination-bar"></div>
    </div>

    <div id="tabUsers" class="tab-panel" style="display:none;">
        <div id="usersContainer">กำลังโหลด...</div>
        <div id="usersPagination" class="pagination-bar"></div>
    </div>

    <div id="tabTags" class="tab-panel" style="display:none;">

        <!-- ส่วนที่ 1: รายการ tag ทั้งหมด แก้ชื่อ/ลบทั้งหมดได้ -->
        <details class="kb-toolbar-section" open>
            <summary>🏷️ Tag ทั้งหมดในระบบ</summary>
            <div class="kb-toolbar-body">
                <div id="tagManagerList">กำลังโหลด...</div>
            </div>
        </details>

        <!-- ส่วนที่ 2: เพิ่ม/ลบ tag ตามช่วง id -->
        <details class="kb-toolbar-section">
            <summary>➕➖ เพิ่ม/ลบ Tag ตามช่วง ID</summary>
            <div class="kb-toolbar-body">
                <p class="ts-note" id="idRangeHint">กำลังเช็คช่วง id ปัจจุบัน...</p>

                <p class="modal-section-label" style="margin-top:0;">เพิ่ม tag ให้ chunk ในช่วง ID</p>
                <div class="tag-range-row">
                    <input type="text" id="rangeAddTagName" placeholder="ชื่อ tag (สร้างใหม่ได้ถ้ายังไม่มี)">
                    <input type="number" id="rangeAddStart" placeholder="ID เริ่ม">
                    <input type="number" id="rangeAddEnd" placeholder="ID สิ้นสุด">
                    <button onclick="addTagToRange()">เพิ่ม</button>
                </div>
                <span id="rangeAddStatus" class="kb-toolbar-status"></span>

                <p class="modal-section-label">ลบ tag ออกจาก chunk ในช่วง ID</p>
                <div class="tag-range-row">
                    <select id="rangeRemoveTagId"><option value="">เลือก tag...</option></select>
                    <input type="number" id="rangeRemoveStart" placeholder="ID เริ่ม">
                    <input type="number" id="rangeRemoveEnd" placeholder="ID สิ้นสุด">
                    <button onclick="removeTagFromRange()" class="danger-btn">ลบ</button>
                </div>
                <span id="rangeRemoveStatus" class="kb-toolbar-status"></span>
            </div>
        </details>

        <!-- ส่วนที่ 3: Scope filter ละเอียด — ใช้ preview ตอนนี้ และเตรียมไว้ให้ AI Agent ใช้ในระยะถัดไป -->
        <details class="kb-toolbar-section">
            <summary>🎯 กำหนดขอบเขต (Scope) — เตรียมไว้สำหรับ AI Agent ในระยะถัดไป</summary>
            <div class="kb-toolbar-body">
                <p class="ts-note">เลือกขอบเขตที่จะทำงานด้วย — เลือก "ทั้งหมด" จะปิดตัวเลือกอื่นอัตโนมัติ (กันเลือกขัดแย้งกัน)</p>

                <label class="scope-option">
                    <input type="radio" name="scopeMode" value="all" checked onchange="onScopeModeChange()">
                    ทั้งหมดใน Knowledge Base
                </label>
                <label class="scope-option">
                    <input type="radio" name="scopeMode" value="tags" onchange="onScopeModeChange()">
                    เฉพาะ tag ที่เลือก (เลือกได้หลายอัน)
                </label>
                <div id="scopeTagList" class="kb-tag-filter-list scope-sub-option"></div>

                <label class="scope-option">
                    <input type="radio" name="scopeMode" value="id_range" onchange="onScopeModeChange()">
                    เฉพาะช่วง ID
                </label>
                <div id="scopeIdRangeRow" class="tag-range-row scope-sub-option">
                    <input type="number" id="scopeStartId" placeholder="ID เริ่ม" oninput="updateScopePreview()">
                    <input type="number" id="scopeEndId" placeholder="ID สิ้นสุด" oninput="updateScopePreview()">
                </div>

                <label class="scope-option">
                    <input type="radio" name="scopeMode" value="untagged" onchange="onScopeModeChange()">
                    เฉพาะที่ยังไม่มี tag เลย
                </label>

                <p class="scope-preview">📊 ตรงกับ <strong id="scopePreviewCount">-</strong> รายการ</p>
            </div>
        </details>
        <!-- ส่วนที่ 4: Backup / Rollback — ต้องมีก่อนให้ AI Agent แตะข้อมูลจริงในระยะถัดไป -->
        <details class="kb-toolbar-section">
            <summary>💾 Backup & Rollback</summary>
            <div class="kb-toolbar-body">
                <p class="ts-note">เก็บ backup ล่าสุดไว้ 2 เวอร์ชัน (เวอร์ชันเก่าสุดถูกลบทิ้งอัตโนมัติเมื่อสร้างใหม่เกิน 2 อัน)</p>
                <button onclick="createKbSnapshot()">📸 สร้าง Backup ตอนนี้</button>
                <span id="snapshotCreateStatus" class="kb-toolbar-status"></span>
                <div id="snapshotList" style="margin-top:12px;">กำลังโหลด...</div>
            </div>
        </details>
        <!-- ส่วนที่ 5: AI Agent — ใช้ scope จากกล่องด้านบน ต้องอ่านคำเตือนก่อนใช้ -->
        <details class="kb-toolbar-section">
            <summary>🤖 AI Agent (มีความเสี่ยง — อ่านคำเตือนก่อนใช้)</summary>
            <div class="kb-toolbar-body">
                <p class="ts-note">Agent จะทำงานภายในขอบเขต (Scope) ที่ตั้งไว้ในกล่อง "🎯 กำหนดขอบเขต" ด้านบน — ตั้ง scope ก่อนมาที่นี่ ดูจำนวนที่ตรง scope ได้จากกล่องด้านบน</p>

                <p class="modal-section-label" style="margin-top:0;">1. เลือกงานที่จะให้ Agent ทำ</p>
                <label class="scope-option">
                    <input type="radio" name="agentAction" value="suggest_tags" checked onchange="onAgentActionChange()">
                    เสนอ/เพิ่ม Tag อัตโนมัติ
                </label>
                <label class="scope-option">
                    <input type="radio" name="agentAction" value="merge_chunks" onchange="onAgentActionChange()">
                    หา chunk ที่ควรยุบรวม
                </label>

                <div id="agentTagOptions" style="margin:8px 0 8px 24px;">
                    <p class="modal-section-label">รูปแบบการดู chunk</p>
                    <label class="scope-option"><input type="radio" name="tagStrategy" value="batch" checked> ดูหลาย chunk พร้อมกัน (เร็วกว่า)</label>
                    <label class="scope-option"><input type="radio" name="tagStrategy" value="per_chunk"> ดูทีละ chunk แยกกัน (ช้ากว่า แม่นกว่า)</label>
                </div>

                <div id="agentMergeOptions" style="display:none; margin:8px 0 8px 24px;">
                    <p class="modal-section-label">วิธีหาคู่ที่ควรรวม</p>
                    <label class="scope-option"><input type="radio" name="mergeStrategy" value="embedding_prefilter" checked> ใช้ embedding คัด candidate ก่อน (เร็ว/ถูกกว่า)</label>
                    <label class="scope-option"><input type="radio" name="mergeStrategy" value="all_pairs"> เทียบทุกคู่ตรงๆ (แม่นกว่า จำกัดไม่เกิน 40 chunk/รอบ)</label>
                </div>

                <p class="modal-section-label">2. เลือกโหมดการทำงาน</p>
                <label class="scope-option"><input type="radio" name="agentMode" value="review" checked> Review — เสนอให้ดูก่อน แก้ไขได้ ค่อยยืนยันทีละอัน</label>
                <label class="scope-option"><input type="radio" name="agentMode" value="autonomous"> Autonomous — ทำงานอัตโนมัติทั้งหมดทันที</label>

                <button onclick="startAgentJob()" class="danger-btn" style="margin-top:12px;">🚀 เริ่มทำงาน</button>
                <span id="agentRunStatus" class="kb-toolbar-status"></span>
            </div>
        </details>

        <!-- ส่วนที่ 6: Review Queue -->
        <details class="kb-toolbar-section" open>
            <summary>📋 รายการรอตรวจสอบจาก Agent (Review Queue)</summary>
            <div class="kb-toolbar-body">
                <div id="agentProposalList">กำลังโหลด...</div>
            </div>
        </details>

        <!-- ส่วนที่ 7: ประวัติการทำงาน -->
        <details class="kb-toolbar-section">
            <summary>📜 ประวัติการทำงานของ Agent</summary>
            <div class="kb-toolbar-body">
                <div id="agentJobList">กำลังโหลด...</div>
            </div>
        </details>
    </div>

    <script src="/static/admin.js"></script>
</body>
</html>
