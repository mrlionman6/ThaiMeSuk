async function askQuestion() {
    const query = document.getElementById("questionInput").value;
    if (!query) return;

    document.getElementById("loading").style.display = "block";
    document.getElementById("answerBox").innerText = "";

    try {
        const response = await fetch("/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query })
        });

        const data = await response.json();

        document.getElementById("loading").style.display = "none";
        document.getElementById("answerBox").innerText = data.answer;

    } catch (error) {
        document.getElementById("loading").style.display = "none";
        document.getElementById("answerBox").innerText = "เกิดข้อผิดพลาด: " + error;
    }
}
