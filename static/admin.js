async function loadLogs() {
    const response = await fetch("/admin/api/logs");
    const data = await response.json();
    const container = document.getElementById("logsContainer");

    if (data.logs.length === 0) {
        container.innerHTML = "<p>ไม่มีรายการรอตรวจสอบ 🎉</p>";
        return;
    }

    container.innerHTML = "";
    data.logs.forEach(log => {
        const div = document.createElement("div");
        div.style = "border:1px solid #ddd; padding:15px; margin-bottom:15px; border-radius:8px;";
        div.innerHTML = `
            <p><strong>คำถาม:</strong> ${log.query}</p>
            <p><strong>คำตอบที่ Claude ตอบ:</strong> ${log.answer}</p>
            <p><strong>คะแนนความมั่นใจ:</strong> ${log.max_score.toFixed(3)}</p>
            <button onclick="approveLog(${log.id})">✅ เพิ่มเข้า Knowledge Base</button>
            <button onclick="rejectLog(${log.id})">❌ ทิ้งไป</button>
        `;
        container.appendChild(div);
    });
}

async function approveLog(id) {
    await fetch("/admin/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ log_id: id })
    });
    loadLogs();
}
