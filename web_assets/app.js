document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }

  const message = form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
    return;
  }

  const submitter = event.submitter;
  if (submitter instanceof HTMLButtonElement && submitter.name === "bulk_action") {
    const selected = form.querySelectorAll("[data-row-check]:checked").length;
    if (!selected) {
      event.preventDefault();
      window.alert(submitter.dataset.confirmBulk || "Bạn chưa chọn bài nào.");
      return;
    }

    if (submitter.value === "delete") {
      const ok = window.confirm(`Bạn chắc chắn muốn xóa ${selected} bài đã chọn?`);
      if (!ok) {
        event.preventDefault();
      }
    }
  }
});

document.addEventListener("input", (event) => {
  const field = event.target;
  if (!(field instanceof HTMLTextAreaElement)) {
    return;
  }

  field.style.height = "auto";
  field.style.height = `${field.scrollHeight}px`;
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }

  if (target.matches("[data-select-all]")) {
    document.querySelectorAll("[data-row-check]").forEach((checkbox) => {
      checkbox.checked = target.checked;
    });
  }

  if (target.matches("[data-row-check]")) {
    const checks = Array.from(document.querySelectorAll("[data-row-check]"));
    const selectAll = document.querySelector("[data-select-all]");
    if (selectAll instanceof HTMLInputElement) {
      selectAll.checked = checks.length > 0 && checks.every((checkbox) => checkbox.checked);
      selectAll.indeterminate = checks.some((checkbox) => checkbox.checked) && !selectAll.checked;
    }
  }
});

const scrollTopButton = document.querySelector("[data-scroll-top]");
if (scrollTopButton instanceof HTMLButtonElement) {
  const syncScrollButton = () => {
    scrollTopButton.classList.toggle("is-visible", window.scrollY > 520);
  };

  scrollTopButton.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("scroll", syncScrollButton, { passive: true });
  syncScrollButton();
}

const chatbot = document.querySelector("[data-chatbot]");
if (chatbot instanceof HTMLElement) {
  const toggleButton = chatbot.querySelector("[data-chat-toggle]");
  const closeButton = chatbot.querySelector("[data-chat-close]");
  const panel = chatbot.querySelector("[data-chat-panel]");
  const form = chatbot.querySelector("[data-chat-form]");
  const input = form instanceof HTMLFormElement ? form.elements.namedItem("message") : null;
  const messages = chatbot.querySelector("[data-chat-messages]");
  const suggestions = chatbot.querySelector("[data-chat-suggestions]");

  const setChatOpen = (open) => {
    chatbot.classList.toggle("is-open", open);
    if (panel instanceof HTMLElement) {
      panel.setAttribute("aria-hidden", open ? "false" : "true");
    }
    if (toggleButton instanceof HTMLButtonElement) {
      toggleButton.setAttribute("aria-expanded", open ? "true" : "false");
    }
    if (open && input instanceof HTMLInputElement) {
      window.setTimeout(() => input.focus(), 80);
    }
  };

  const appendMessage = (role, text, articles = []) => {
    if (!(messages instanceof HTMLElement)) {
      return;
    }
    const item = document.createElement("article");
    item.className = `chat-message ${role}`;

    const paragraph = document.createElement("p");
    paragraph.textContent = text || "";
    item.appendChild(paragraph);

    if (articles.length) {
      const list = document.createElement("div");
      list.className = "chat-article-list";
      articles.forEach((article) => {
        list.appendChild(renderChatArticle(article));
      });
      item.appendChild(list);
    }

    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
  };

  const renderChatArticle = (article) => {
    const card = document.createElement("a");
    card.className = "chat-article-card";
    card.href = article.url || "/client";
    card.target = article.url ? "_blank" : "_self";
    card.rel = "noopener";

    const imageWrap = document.createElement("span");
    imageWrap.className = "chat-article-image";
    if (article.thumbnail) {
      const image = document.createElement("img");
      image.src = article.thumbnail;
      image.alt = article.title || "IEC News";
      image.loading = "lazy";
      image.addEventListener("error", () => {
        image.remove();
        imageWrap.textContent = "IEC";
        imageWrap.classList.add("is-fallback");
      }, { once: true });
      imageWrap.appendChild(image);
    } else {
      imageWrap.textContent = "IEC";
      imageWrap.classList.add("is-fallback");
    }

    const body = document.createElement("span");
    body.className = "chat-article-body";

    const meta = document.createElement("small");
    meta.textContent = [article.source, article.content_topic || article.category].filter(Boolean).join(" • ");

    const title = document.createElement("strong");
    title.textContent = article.title || "Không có tiêu đề";

    const summary = document.createElement("span");
    summary.textContent = article.summary || "Chưa có tóm tắt.";

    const linkText = document.createElement("em");
    linkText.textContent = "Đọc bài";

    body.append(meta, title, summary, linkText);
    card.append(imageWrap, body);
    return card;
  };

  const appendLoading = () => {
    if (!(messages instanceof HTMLElement)) {
      return null;
    }
    const item = document.createElement("article");
    item.className = "chat-message bot loading";
    item.innerHTML = "<p>IEC News Assistant đang tìm bài phù hợp...</p>";
    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
    return item;
  };

  const sendChatMessage = async (message) => {
    const cleanMessage = String(message || "").trim().slice(0, 500);
    if (!cleanMessage) {
      return;
    }
    setChatOpen(true);
    appendMessage("user", cleanMessage);
    if (input instanceof HTMLInputElement) {
      input.value = "";
    }
    const loading = appendLoading();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: cleanMessage }),
      });
      const data = await response.json();
      if (loading) {
        loading.remove();
      }
      appendMessage("bot", data.answer || "Tôi chưa tìm thấy câu trả lời phù hợp.", data.articles || []);
    } catch (error) {
      if (loading) {
        loading.remove();
      }
      appendMessage("bot", "Tôi chưa kết nối được với chatbot lúc này. Bạn hãy thử lại sau nhé.");
    }
  };

  if (toggleButton instanceof HTMLButtonElement) {
    toggleButton.addEventListener("click", () => {
      setChatOpen(!chatbot.classList.contains("is-open"));
    });
  }

  if (closeButton instanceof HTMLButtonElement) {
    closeButton.addEventListener("click", () => setChatOpen(false));
  }

  if (form instanceof HTMLFormElement && input instanceof HTMLInputElement) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      sendChatMessage(input.value);
    });
  }

  if (suggestions instanceof HTMLElement) {
    suggestions.addEventListener("click", (event) => {
      const target = event.target;
      if (target instanceof HTMLButtonElement && target.dataset.chatSuggestion) {
        sendChatMessage(target.dataset.chatSuggestion);
      }
    });
  }
}
