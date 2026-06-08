(function () {
    const page = document.body.dataset.page;
    const numberFormatter = new Intl.NumberFormat("en-US");
    const moneyFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
    const orange = "#ff6a00";
    const orangeSoft = "#ff9a3d";
    const green = "#4ade80";
    const blue = "#60a5fa";
    const purple = "#a78bfa";
    const yellow = "#f59e0b";
    const gridColor = "rgba(255,255,255,0.09)";
    const labelColor = "#c5cad3";
    const charts = {};
    const dashboardRefreshMs = 5000;
    const liveImagePrefix = "__VOUCHR_IMAGE_ATTACHMENT__:";
    let dashboardRequestInFlight = false;
    let dashboardRefreshQueued = false;
    let dashboardRangeDays = 7;

    function formatNumber(value) {
        return numberFormatter.format(Number(value || 0));
    }

    function setText(selector, value) {
        const node = document.querySelector(selector);
        if (node) {
            node.textContent = value;
        }
    }

    function setAllText(selector, value) {
        document.querySelectorAll(selector).forEach((node) => {
            node.textContent = value;
        });
    }

    function updateSearch() {
        const search = document.getElementById("adminSearch");
        const resultsPanel = document.getElementById("adminSearchResults");
        if (!search || !resultsPanel) {
            return;
        }

        let debounceTimer;
        let selectedIndex = -1;

        function filterCurrentTable(query) {
            document.querySelectorAll(".searchable tbody tr:not(.voucher-filter-empty)").forEach((row) => {
                row.style.display = row.textContent.toLowerCase().includes(query) ? "" : "none";
            });
        }

        function closeResults() {
            resultsPanel.hidden = true;
            resultsPanel.innerHTML = "";
            search.setAttribute("aria-expanded", "false");
            selectedIndex = -1;
        }

        function selectResult(index) {
            const items = [...resultsPanel.querySelectorAll(".search-result-item")];
            if (!items.length) {
                return;
            }
            selectedIndex = Math.max(0, Math.min(index, items.length - 1));
            items.forEach((item, itemIndex) => {
                item.classList.toggle("is-selected", itemIndex === selectedIndex);
            });
            items[selectedIndex].scrollIntoView({ block: "nearest" });
        }

        function renderResults(results) {
            selectedIndex = -1;
            if (!results.length) {
                resultsPanel.innerHTML = '<div class="search-empty">No matching users, merchants, vouchers, or tickets.</div>';
            } else {
                resultsPanel.innerHTML = results.map((result) => `
                    <a class="search-result-item" href="${escapeHtml(result.url || "#")}" role="option">
                        <span class="search-result-copy">
                            <strong>${escapeHtml(result.title || "Result")}</strong>
                            <span>${escapeHtml(result.subtitle || "")}</span>
                        </span>
                        <span class="search-result-type">${escapeHtml(result.type || "Result")}</span>
                    </a>
                `).join("");
            }
            resultsPanel.hidden = false;
            search.setAttribute("aria-expanded", "true");
        }

        async function findResults(query) {
            try {
                const response = await fetch(`/api/admin/search?q=${encodeURIComponent(query)}`, {
                    credentials: "same-origin",
                    cache: "no-store",
                });
                if (!response.ok || search.value.trim() !== query) {
                    return;
                }
                const data = await response.json();
                renderResults(data.results || []);
            } catch (error) {
                closeResults();
            }
        }

        search.addEventListener("input", () => {
            const rawQuery = search.value.trim();
            const query = rawQuery.toLowerCase();
            filterCurrentTable(query);
            clearTimeout(debounceTimer);
            if (rawQuery.length < 2) {
                closeResults();
                return;
            }
            debounceTimer = setTimeout(() => findResults(rawQuery), 180);
        });

        search.addEventListener("keydown", (event) => {
            const items = [...resultsPanel.querySelectorAll(".search-result-item")];
            if (event.key === "ArrowDown" && items.length) {
                event.preventDefault();
                selectResult(selectedIndex + 1);
            } else if (event.key === "ArrowUp" && items.length) {
                event.preventDefault();
                selectResult(selectedIndex <= 0 ? items.length - 1 : selectedIndex - 1);
            } else if (event.key === "Enter" && selectedIndex >= 0 && items[selectedIndex]) {
                event.preventDefault();
                items[selectedIndex].click();
            } else if (event.key === "Escape") {
                closeResults();
            }
        });

        document.addEventListener("click", (event) => {
            if (!event.target.closest(".search-box")) {
                closeResults();
            }
        });

        const initialQuery = new URLSearchParams(window.location.search).get("search");
        if (initialQuery) {
            search.value = initialQuery;
            filterCurrentTable(initialQuery.toLowerCase());
        }
    }

    function formatClientDateRange(days) {
        const end = new Date();
        const start = new Date();
        start.setDate(end.getDate() - days + 1);
        const sameYear = start.getFullYear() === end.getFullYear();
        const startOptions = sameYear
            ? { month: "short", day: "2-digit" }
            : { month: "short", day: "2-digit", year: "numeric" };
        const endOptions = { month: "short", day: "2-digit", year: "numeric" };
        return `${start.toLocaleDateString("en-US", startOptions)} - ${end.toLocaleDateString("en-US", endOptions)}`;
    }

    function updateRangeLabels(days) {
        setText("[data-growth-range-label]", `Last ${days} Days`);
        setText("[data-category-range-label]", days === 7 ? "This Week" : `Last ${days} Days`);
    }

    function initDateRangePicker() {
        const picker = document.getElementById("adminDateRange");
        if (!picker) {
            return;
        }
        const validRanges = [7, 30, 90];
        const queryDays = Number(new URLSearchParams(window.location.search).get("days"));
        const storedDays = Number(window.localStorage.getItem("vouchrAdminDateRange"));
        dashboardRangeDays = validRanges.includes(queryDays)
            ? queryDays
            : (validRanges.includes(storedDays) ? storedDays : 7);
        picker.value = String(dashboardRangeDays);
        setText("[data-date-range]", formatClientDateRange(dashboardRangeDays));
        updateRangeLabels(dashboardRangeDays);

        picker.addEventListener("change", () => {
            dashboardRangeDays = validRanges.includes(Number(picker.value)) ? Number(picker.value) : 7;
            window.localStorage.setItem("vouchrAdminDateRange", String(dashboardRangeDays));
            if (page !== "dashboard") {
                window.location.assign(`/admin/dashboard?days=${dashboardRangeDays}`);
                return;
            }
            const url = new URL(window.location.href);
            url.searchParams.set("days", String(dashboardRangeDays));
            window.history.replaceState({}, "", url);
            setText("[data-date-range]", formatClientDateRange(dashboardRangeDays));
            updateRangeLabels(dashboardRangeDays);
            loadDashboard();
        });
    }

    function initTopbarMenus() {
        const menus = [...document.querySelectorAll(".topbar-menu")];
        if (!menus.length) {
            return;
        }

        function closeMenus(exceptMenu = null) {
            menus.forEach((menu) => {
                if (menu === exceptMenu) {
                    return;
                }
                const trigger = menu.querySelector(".topbar-menu-trigger");
                const dropdown = menu.querySelector(".topbar-dropdown");
                if (trigger && dropdown) {
                    trigger.setAttribute("aria-expanded", "false");
                    dropdown.hidden = true;
                }
            });
        }

        menus.forEach((menu) => {
            const trigger = menu.querySelector(".topbar-menu-trigger");
            const dropdown = menu.querySelector(".topbar-dropdown");
            if (!trigger || !dropdown) {
                return;
            }
            trigger.addEventListener("click", (event) => {
                event.stopPropagation();
                const willOpen = dropdown.hidden;
                closeMenus(menu);
                dropdown.hidden = !willOpen;
                trigger.setAttribute("aria-expanded", String(willOpen));
            });
            dropdown.addEventListener("click", (event) => event.stopPropagation());
        });

        document.addEventListener("click", () => closeMenus());
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeMenus();
            }
        });
    }

    function initVoucherFilters() {
        const filterBar = document.querySelector(".voucher-filter-bar");
        const table = document.querySelector(".voucher-directory-table");
        if (!filterBar || !table) {
            return;
        }

        const buttons = [...filterBar.querySelectorAll("[data-voucher-filter]")];
        const rows = [...table.querySelectorAll("[data-voucher-row]")];
        const emptyRow = table.querySelector(".voucher-filter-empty");
        const countLabel = document.querySelector(".voucher-count");
        const activeTotal = document.querySelector("[data-voucher-active-total]");
        const search = document.getElementById("adminSearch");
        let activeFilter = "all";
        let toastTimer;

        function showActionToast(message, isError = false) {
            let toast = document.querySelector(".voucher-action-toast");
            if (!toast) {
                toast = document.createElement("div");
                toast.className = "voucher-action-toast";
                toast.setAttribute("role", "status");
                document.body.appendChild(toast);
            }
            toast.textContent = message;
            toast.classList.toggle("error", isError);
            toast.classList.add("show");
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
        }

        function isExpired(row) {
            if (row.dataset.status === "expired") {
                return true;
            }
            const expiry = row.dataset.expiry;
            if (!expiry) {
                return false;
            }
            const today = new Date();
            const localToday = [
                today.getFullYear(),
                String(today.getMonth() + 1).padStart(2, "0"),
                String(today.getDate()).padStart(2, "0"),
            ].join("-");
            return expiry < localToday;
        }

        function matchesFilter(row, filter) {
            if (filter === "active") {
                return row.dataset.status === "active";
            }
            if (filter === "flagged") {
                return row.dataset.riskStatus === "flagged"
                    || !["", "none"].includes(row.dataset.riskLevel);
            }
            if (filter === "hidden") {
                return row.dataset.status === "hidden";
            }
            if (filter === "expired") {
                return isExpired(row);
            }
            return true;
        }

        function updateCounts() {
            ["all", "active", "flagged", "hidden", "expired"].forEach((filter) => {
                setText(`[data-filter-count="${filter}"]`, rows.filter((row) => matchesFilter(row, filter)).length);
            });
            if (activeTotal) {
                activeTotal.textContent = rows.filter((row) => matchesFilter(row, "active")).length;
            }
        }

        function applyFilters() {
            const query = String(search?.value || "").trim().toLowerCase();
            let visibleCount = 0;
            rows.forEach((row) => {
                const matchesSearch = !query || row.textContent.toLowerCase().includes(query);
                const visible = matchesSearch && matchesFilter(row, activeFilter);
                row.hidden = !visible;
                row.style.display = visible ? "" : "none";
                if (visible) {
                    visibleCount += 1;
                }
            });
            if (emptyRow) {
                emptyRow.hidden = visibleCount !== 0;
                emptyRow.style.display = visibleCount === 0 ? "" : "none";
            }
            if (countLabel) {
                countLabel.textContent = activeFilter === "all" && !query
                    ? `${rows.length} vouchers`
                    : `${visibleCount} of ${rows.length} vouchers`;
            }
        }

        buttons.forEach((button) => {
            button.addEventListener("click", () => {
                activeFilter = button.dataset.voucherFilter || "all";
                buttons.forEach((item) => item.classList.toggle("active", item === button));
                applyFilters();
            });
        });

        table.querySelectorAll("[data-voucher-action-form]").forEach((form) => {
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                const submitter = event.submitter;
                if (!submitter) {
                    return;
                }

                const row = form.closest("[data-voucher-row]");
                const previousStatus = row?.dataset.status || "";
                const formData = new FormData(form);
                formData.set("action", submitter.value);
                form.querySelectorAll("button").forEach((button) => {
                    button.disabled = true;
                });

                try {
                    const response = await fetch("/vouchers", {
                        method: "POST",
                        body: formData,
                        credentials: "same-origin",
                        headers: { "X-Requested-With": "XMLHttpRequest" },
                    });
                    const data = await response.json();
                    if (!response.ok || !data.success) {
                        throw new Error(data.error || "Voucher update failed.");
                    }

                    const status = data.status;
                    row.dataset.status = status;
                    const badge = row.querySelector("[data-voucher-status-badge]");
                    if (badge) {
                        badge.textContent = status.replaceAll("_", " ");
                        badge.classList.remove("green", "blue", "red");
                        badge.classList.add(status === "active" ? "green" : status === "removed" ? "red" : "blue");
                    }

                    form.innerHTML = `
                        <input type="hidden" name="voucher_id" value="${formData.get("voucher_id")}">
                        ${status !== "active" ? '<button class="voucher-action restore" name="action" value="active">Restore</button>' : ""}
                        ${status !== "hidden" ? '<button class="voucher-action" name="action" value="hidden">Hide</button>' : ""}
                        ${status !== "removed" ? '<button class="voucher-action remove" name="action" value="removed">Remove</button>' : ""}
                    `;
                    updateCounts();
                    applyFilters();
                    showActionToast(data.message || `Voucher changed from ${previousStatus} to ${status}.`);
                } catch (error) {
                    form.querySelectorAll("button").forEach((button) => {
                        button.disabled = false;
                    });
                    showActionToast(error.message || "Voucher update failed.", true);
                }
            });
        });
        search?.addEventListener("input", applyFilters);
        updateCounts();
        applyFilters();
    }

    function initAnnouncementPreview() {
        const titleInput = document.getElementById("announcementTitle");
        const messageInput = document.getElementById("announcementMessage");
        const audienceInput = document.getElementById("announcementAudience");
        const statusInput = document.getElementById("announcementStatus");
        const scheduleInput = document.getElementById("announcementSchedule");
        const submitButton = document.getElementById("announcementSubmitButton");
        const previewTitle = document.getElementById("announcementPreviewTitle");
        const previewMessage = document.getElementById("announcementPreviewMessage");
        const previewMeta = document.getElementById("announcementPreviewMeta");

        if (!titleInput || !messageInput || !previewTitle || !previewMessage || !previewMeta) {
            return;
        }

        const audienceLabels = {
            all_users: "All Users",
            customers: "Customers",
            merchants: "Merchants",
            new_users: "New Users",
            high_activity_users: "High Activity Users",
        };

        function updatePreview() {
            const title = titleInput.value.trim() || "Announcement preview";
            const message = messageInput.value.trim() || "Published announcements can appear in the customer notification area.";
            const audience = audienceLabels[audienceInput.value] || audienceInput.value || "All Users";
            const status = statusInput.value || "draft";
            const schedule = scheduleInput.value ? ` - ${scheduleInput.value.replace("T", " ")}` : "";

            previewTitle.textContent = title;
            previewMessage.textContent = message;
            previewMeta.textContent = `${audience} - ${status}${schedule}`;
            if (submitButton) {
                submitButton.textContent = status === "published" || status === "scheduled"
                    ? "Announce"
                    : "Save Announcement";
            }
        }

        [titleInput, messageInput, audienceInput, statusInput, scheduleInput].forEach((input) => {
            input.addEventListener("input", updatePreview);
            input.addEventListener("change", updatePreview);
        });
        updatePreview();
    }

    function initAdminSettings() {
        const settingsGrid = document.querySelector(".settings-grid");
        if (!settingsGrid) {
            return;
        }

        const status = document.getElementById("settingsStatus");
        const notificationSave = document.getElementById("saveNotificationSettings");
        const maintenanceToggle = document.getElementById("maintenanceToggle");
        const runBackupBtn = document.getElementById("runBackupBtn");
        const backupFrequency = document.getElementById("backupFrequency");
        const backupRetention = document.getElementById("backupRetention");
        const lastBackupText = document.getElementById("lastBackupText");

        function setStatus(message, tone) {
            if (!status) return;
            status.textContent = message;
            status.dataset.tone = tone || "info";
        }

        function toggleButton(button) {
            button.classList.toggle("on");
            return button.classList.contains("on");
        }

        settingsGrid.querySelectorAll(".admin-toggle").forEach((button) => {
            button.addEventListener("click", () => {
                toggleButton(button);
                if (button === maintenanceToggle) {
                    saveMaintenanceSettings();
                }
            });
        });

        async function saveNotificationSettings() {
            const payload = {};
            settingsGrid.querySelectorAll("[data-setting-key]").forEach((button) => {
                payload[button.dataset.settingKey] = button.classList.contains("on");
            });
            setStatus("Saving notifications...");
            try {
                const response = await fetch("/api/admin/settings/notifications", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error(data.error || "Save failed");
                setStatus(data.message || "Notification preferences saved", "success");
            } catch (_) {
                setStatus("Could not save notifications", "error");
            }
        }

        async function saveMaintenanceSettings() {
            const payload = {
                maintenance_mode: maintenanceToggle && maintenanceToggle.classList.contains("on"),
                backup_frequency: backupFrequency ? backupFrequency.value : "Daily",
                backup_retention: backupRetention ? backupRetention.value : "30 days",
            };
            setStatus("Saving maintenance settings...");
            try {
                const response = await fetch("/api/admin/settings/maintenance", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error(data.error || "Save failed");
                setStatus(data.message || "Maintenance settings saved", "success");
            } catch (_) {
                setStatus("Could not save maintenance settings", "error");
            }
        }

        async function runBackup() {
            if (!runBackupBtn) return;
            runBackupBtn.disabled = true;
            setStatus("Creating backup...");
            try {
                const response = await fetch("/api/admin/settings/backup", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({}),
                });
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error(data.error || "Backup failed");
                if (lastBackupText && data.backup && data.backup.created_at) {
                    lastBackupText.textContent = data.backup.created_at;
                }
                setStatus(data.message || "Manual backup created", "success");
            } catch (_) {
                setStatus("Could not create backup", "error");
            } finally {
                runBackupBtn.disabled = false;
            }
        }

        if (notificationSave) {
            notificationSave.addEventListener("click", saveNotificationSettings);
        }
        if (backupFrequency) {
            backupFrequency.addEventListener("change", saveMaintenanceSettings);
        }
        if (backupRetention) {
            backupRetention.addEventListener("change", saveMaintenanceSettings);
        }
        if (runBackupBtn) {
            runBackupBtn.addEventListener("click", runBackup);
        }

        document.querySelectorAll("[data-settings-toast]").forEach((button) => {
            button.addEventListener("click", () => setStatus(button.dataset.settingsToast || "Saved for demo", "info"));
        });
    }

    function statusBadgeClass(status) {
        const normalized = String(status || "").toLowerCase();
        if (normalized === "waiting") return "red";
        if (normalized === "active") return "green";
        return "blue";
    }

    function parseLiveImageMessage(rawMessage) {
        const raw = String(rawMessage || "");
        if (!raw.startsWith(liveImagePrefix)) {
            return { text: raw, attachment: null };
        }

        try {
            const payload = JSON.parse(raw.slice(liveImagePrefix.length));
            const attachment = payload && payload.dataUrl
                ? { name: payload.name || "Attached image", dataUrl: payload.dataUrl }
                : null;
            return { text: String((payload && payload.text) || ""), attachment };
        } catch (_) {
            return { text: raw, attachment: null };
        }
    }

    function liveImageSummary(rawMessage, fallback) {
        const parsed = parseLiveImageMessage(rawMessage);
        if (!parsed.attachment) return rawMessage || fallback || "Live support chat";
        return parsed.text ? `${parsed.text} - Image attached` : "Image attached";
    }

    function liveMessageHtml(rawMessage) {
        const parsed = parseLiveImageMessage(rawMessage);
        const parts = [];
        if (parsed.text) {
            parts.push(`<span class="message-text">${escapeHtml(parsed.text)}</span>`);
        }
        if (parsed.attachment && parsed.attachment.dataUrl) {
            const name = parsed.attachment.name || "Attached image";
            const source = parsed.attachment.dataUrl || "";
            parts.push(`
                <a class="message-attachment live-message-attachment" href="${escapeHtml(source)}" target="_blank" rel="noopener">
                    <img src="${escapeHtml(source)}" alt="${escapeHtml(name)}">
                    <span>${escapeHtml(name)}</span>
                </a>
            `);
        }
        return parts.join("") || `<span class="message-text">Image attached</span>`;
    }

    function initAdminLiveSupport() {
        const list = document.getElementById("adminLiveSessionList");
        const panel = document.getElementById("adminLivePanel");
        if (!list || !panel) {
            return;
        }

        let selectedSessionId = panel.dataset.selectedSessionId || "";
        const messagesBox = document.getElementById("adminLiveMessages");
        const customerTitle = document.getElementById("adminLiveCustomer");
        const metaText = document.getElementById("adminLiveMeta");
        const statusBadge = document.getElementById("adminLiveStatus");
        const acceptBtn = document.getElementById("adminAcceptLiveBtn");
        const resolveBtn = document.getElementById("adminResolveLiveBtn");
        const convertBtn = document.getElementById("adminConvertLiveBtn");
        const replyForm = document.getElementById("adminLiveReplyForm");
        const replyInput = document.getElementById("adminLiveReplyInput");
        let lastMessageSignature = "";

        function renderSessionList(sessions) {
            const statuses = ["waiting", "active", "resolved", "ended"];
            const html = statuses.map((status) => {
                const rows = (sessions || []).filter((item) => String(item.status || "").toLowerCase() === status);
                return `
                    <h3 class="live-section-title">${status.charAt(0).toUpperCase() + status.slice(1)}</h3>
                    ${rows.map((item) => `
                        <a class="ticket-card live-session-card ${String(item.id) === String(selectedSessionId) ? "active" : ""}" href="/support/live?live_session_id=${encodeURIComponent(item.id)}" data-live-session-id="${escapeHtml(item.id)}">
                            <strong>${escapeHtml(item.user_name || "Customer")}</strong>
                            <span class="badge ${statusBadgeClass(item.status)}">${escapeHtml(String(item.status || "waiting").replace("_", " "))}</span>
                            <p class="muted">${escapeHtml(liveImageSummary(item.last_message, item.subject || "Live support chat"))}</p>
                            <small>${escapeHtml(item.last_message_at || item.updated_at || "")}</small>
                        </a>
                    `).join("")}
                `;
            }).join("");
            list.innerHTML = html || `<p class="muted">No live chats yet.</p>`;
        }

        function renderMessages(messages) {
            if (!messagesBox) return;
            const signature = JSON.stringify((messages || []).map((message) => [message.id, message.message, message.sender_role]));
            if (signature === lastMessageSignature) return;
            lastMessageSignature = signature;
            messagesBox.innerHTML = (messages || []).map((message) => `
                <div class="message ${escapeHtml(message.sender_role || "system")}">
                    <small>${escapeHtml(message.sender_role || "system")} - ${escapeHtml(message.created_at || "")}</small>
                    ${liveMessageHtml(message.message || "")}
                </div>
            `).join("");
            messagesBox.scrollTop = messagesBox.scrollHeight;
        }

        function updateSelectedSession(session) {
            if (!session) return;
            selectedSessionId = String(session.id || selectedSessionId);
            panel.dataset.selectedSessionId = selectedSessionId;
            if (customerTitle) customerTitle.textContent = session.user_name || "Customer";
            if (metaText) metaText.textContent = `${session.user_email || "No email"} - ${String(session.status || "waiting").replace("_", " ")}`;
            if (statusBadge) {
                statusBadge.textContent = String(session.status || "waiting").replace("_", " ");
                statusBadge.className = `badge ${statusBadgeClass(session.status)}`;
            }
        }

        async function loadSessions() {
            try {
                const response = await fetch("/api/admin/live-support/sessions", { credentials: "same-origin" });
                if (!response.ok) return;
                const data = await response.json();
                renderSessionList(data.sessions || []);
                const badge = document.getElementById("liveChatWaitingBadge");
                if (badge) badge.textContent = data.waiting_count || 0;
            } catch (_) {}
        }

        async function loadMessages() {
            if (!selectedSessionId || !messagesBox) return;
            try {
                const response = await fetch(`/api/admin/live-support/${encodeURIComponent(selectedSessionId)}/messages`, { credentials: "same-origin" });
                if (!response.ok) return;
                const data = await response.json();
                updateSelectedSession(data.session);
                renderMessages(data.messages || []);
            } catch (_) {}
        }

        async function postLiveAction(action, body) {
            if (!selectedSessionId) return null;
            const options = {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
            };
            if (body) {
                options.body = JSON.stringify(body);
            }
            const response = await fetch(`/api/admin/live-support/${encodeURIComponent(selectedSessionId)}/${action}`, options);
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || "Live support action failed");
            }
            if (data.session) updateSelectedSession(data.session);
            if (data.messages) renderMessages(data.messages);
            await loadSessions();
            return data;
        }

        list.addEventListener("click", (event) => {
            const card = event.target.closest("[data-live-session-id]");
            if (!card || !messagesBox) return;
            event.preventDefault();
            selectedSessionId = card.dataset.liveSessionId;
            panel.dataset.selectedSessionId = selectedSessionId;
            lastMessageSignature = "";
            history.replaceState(null, "", `/support/live?live_session_id=${encodeURIComponent(selectedSessionId)}`);
            loadSessions();
            loadMessages();
        });

        if (acceptBtn) {
            acceptBtn.addEventListener("click", () => postLiveAction("accept").catch(() => {}));
        }
        if (resolveBtn) {
            resolveBtn.addEventListener("click", () => postLiveAction("resolve").catch(() => {}));
        }
        if (convertBtn) {
            convertBtn.addEventListener("click", async () => {
                try {
                    const data = await postLiveAction("convert-ticket");
                    if (data && data.ticket_url) {
                        window.location.href = data.ticket_url;
                    }
                } catch (_) {}
            });
        }
        if (replyForm && replyInput) {
            replyForm.addEventListener("submit", async (event) => {
                event.preventDefault();
                const message = replyInput.value.trim();
                if (!message) return;
                replyInput.disabled = true;
                try {
                    await postLiveAction("send", { message });
                    replyInput.value = "";
                } catch (_) {}
                replyInput.disabled = false;
                replyInput.focus();
            });
        }

        loadSessions();
        loadMessages();
        setInterval(loadSessions, 3000);
        setInterval(loadMessages, 2000);
    }

    function actionClass(action) {
        const lower = String(action || "").toLowerCase();
        if (lower.includes("created") || lower.includes("approved")) {
            return "green";
        }
        if (lower.includes("redeemed") || lower.includes("support") || lower.includes("ticket")) {
            return "blue";
        }
        if (lower.includes("flagged") || lower.includes("hidden") || lower.includes("spike") || lower.includes("rejected")) {
            return "red";
        }
        return "";
    }

    function partnerInitials(name) {
        return String(name || "VA")
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0].toUpperCase())
            .join("") || "VA";
    }

    function renderKpis(data) {
        const kpis = data.kpis || {};
        const deltas = data.kpi_deltas || {};
        Object.entries(kpis).forEach(([key, value]) => {
            setText(`[data-kpi="${key}"]`, formatNumber(value));
        });
        Object.entries(deltas).forEach(([key, delta]) => {
            const element = document.querySelector(`[data-delta="${key}"]`);
            if (!element) {
                return;
            }
            const normalized = typeof delta === "object"
                ? delta
                : { direction: "up", value: String(delta || "0").replace("%", "") };
            const direction = ["up", "down", "flat"].includes(normalized.direction)
                ? normalized.direction
                : "flat";
            const value = Number(normalized.value || 0);
            element.classList.remove("up", "down", "flat");
            element.classList.add(direction);
            element.textContent = direction === "flat"
                ? "no change"
                : `${direction} ${value}%`;
        });
        // Keep the visible range tied to the user's selection during auto-refresh.
        setText("[data-date-range]", formatClientDateRange(dashboardRangeDays));
        setAllText("[data-notification-count]", data.notification_count || 0);
        setText("[data-ai-alert-count]", data.ai_review_count || 0);
        setText("[data-support-alert-count]", data.support_ticket_count || 0);
        updateRangeLabels(dashboardRangeDays);
    }

    function renderRecentActivity(rows) {
        const tbody = document.getElementById("recentActivityBody");
        if (!tbody) {
            return;
        }
        tbody.innerHTML = "";
        const items = rows || [];
        if (!items.length) {
            tbody.innerHTML = `
                <tr class="empty-table-row">
                    <td colspan="5">No merchant activity has been recorded yet.</td>
                </tr>
            `;
            return;
        }
        items.forEach((item) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>
                    <div class="partner-cell">
                        <span class="partner-logo">${partnerInitials(item.partner)}</span>
                        <span>${item.partner || "Partner"}</span>
                    </div>
                </td>
                <td><span class="action-pill ${actionClass(item.action)}">${item.action || "Updated"}</span></td>
                <td>${item.details || "Platform activity"}</td>
                <td>${item.by || "System"}</td>
                <td>${item.time || "Just now"}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function riskClass(level) {
        return `risk-${String(level || "low").toLowerCase()}`;
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function renderFlaggedVouchers(rows) {
        const list = document.getElementById("flaggedVoucherList");
        if (!list) {
            return;
        }
        list.innerHTML = "";
        const items = rows || [];
        if (!items.length) {
            list.innerHTML = `
                <div class="flagged-row empty">
                    <div class="merchant-avatar">AI</div>
                    <div class="flagged-info">
                        <strong>No flagged vouchers</strong>
                        <span>AI Review is clear right now.</span>
                    </div>
                </div>
            `;
            return;
        }
        items.slice(0, 3).forEach((item) => {
            const node = document.createElement("div");
            node.className = "flagged-row";
            const merchant = item.merchant || "Merchant";
            const risk = item.risk_level || "Low";
            node.innerHTML = `
                <div class="merchant-avatar">${escapeHtml(partnerInitials(merchant))}</div>
                <div class="flagged-info">
                    <strong>${escapeHtml(item.voucher || "Voucher")}</strong>
                    <span>${escapeHtml(merchant)} - ${escapeHtml(item.reason || "Needs review")}</span>
                </div>
                <span class="risk-badge ${riskClass(risk)}">${escapeHtml(risk)}</span>
                <a class="review-btn" href="${escapeHtml(item.review_url || "/ai-review")}">Review</a>
            `;
            list.appendChild(node);
        });
    }

    function renderInsight(data) {
        setText("[data-insight]", data.insight || "Platform activity looks stable.");
    }

    function renderSystemStatus(data) {
        const status = data.system_status || {};
        const list = document.getElementById("systemStatusList");
        if (list) {
            const labels = [
                ["web_application", "Web Application"],
                ["api_services", "API Services"],
                ["database", "Database"],
                ["qr_redemption", "QR Redemption"],
            ];
            list.innerHTML = "";
            labels.forEach(([key, label]) => {
                const row = document.createElement("div");
                row.className = "status-row";
                row.innerHTML = `<span class="status-dot"></span><span>${label}</span><span class="status-value">${status[key] || "Operational"}</span>`;
                list.appendChild(row);
            });
        }
        setText("[data-uptime]", status.uptime || "0m");
        setText("[data-uptime-label]", status.uptime_label || "Admin Session");
    }

    function chartOptions(extra) {
        return Object.assign({
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(15, 20, 27, 0.95)",
                    titleColor: "#fff",
                    bodyColor: "#dfe5ef",
                    borderColor: "rgba(255,255,255,0.12)",
                    borderWidth: 1,
                    padding: 12,
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: labelColor, maxRotation: 0 },
                    border: { color: gridColor },
                },
                y: {
                    grid: { color: gridColor },
                    ticks: { color: labelColor },
                    border: { color: gridColor },
                },
            },
        }, extra || {});
    }

    function drawFallbackLine(canvas, points) {
        const context = canvas && canvas.getContext && canvas.getContext("2d");
        if (!context || !points.length) {
            return;
        }
        const width = canvas.width = canvas.offsetWidth * devicePixelRatio;
        const height = canvas.height = canvas.offsetHeight * devicePixelRatio;
        const padding = 34 * devicePixelRatio;
        const max = Math.max(...points.map((point) => point.users));
        const min = Math.min(...points.map((point) => point.users));
        context.clearRect(0, 0, width, height);
        context.strokeStyle = orange;
        context.lineWidth = 3 * devicePixelRatio;
        context.beginPath();
        points.forEach((point, index) => {
            const x = padding + ((width - padding * 2) * index / Math.max(1, points.length - 1));
            const y = height - padding - ((height - padding * 2) * (point.users - min) / Math.max(1, max - min));
            if (index === 0) {
                context.moveTo(x, y);
            } else {
                context.lineTo(x, y);
            }
        });
        context.stroke();
    }

    function drawFallbackBars(canvas, rows) {
        const context = canvas && canvas.getContext && canvas.getContext("2d");
        if (!context || !rows.length) {
            return;
        }
        const width = canvas.width = canvas.offsetWidth * devicePixelRatio;
        const height = canvas.height = canvas.offsetHeight * devicePixelRatio;
        const padding = 34 * devicePixelRatio;
        const max = Math.max(...rows.map((row) => row.redemptions));
        const barWidth = (width - padding * 2) / rows.length * 0.58;
        context.clearRect(0, 0, width, height);
        rows.forEach((row, index) => {
            const x = padding + ((width - padding * 2) * index / rows.length) + barWidth * 0.35;
            const barHeight = (height - padding * 2) * row.redemptions / Math.max(1, max);
            const y = height - padding - barHeight;
            const gradient = context.createLinearGradient(0, y, 0, height - padding);
            gradient.addColorStop(0, orangeSoft);
            gradient.addColorStop(1, orange);
            context.fillStyle = gradient;
            context.fillRect(x, y, barWidth, barHeight);
        });
    }

    function drawFallbackDonut(canvas, rows) {
        const context = canvas && canvas.getContext && canvas.getContext("2d");
        if (!context || !rows.length) {
            return;
        }
        const colors = [green, blue, yellow, purple, "#ef4444"];
        const width = canvas.width = canvas.offsetWidth * devicePixelRatio;
        const height = canvas.height = canvas.offsetHeight * devicePixelRatio;
        const radius = Math.min(width, height) * 0.36;
        const centerX = width / 2;
        const centerY = height / 2;
        const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0) || 1;
        let start = -Math.PI / 2;
        context.clearRect(0, 0, width, height);
        rows.forEach((row, index) => {
            const slice = Number(row.count || 0) / total * Math.PI * 2;
            context.beginPath();
            context.arc(centerX, centerY, radius, start, start + slice);
            context.lineWidth = radius * 0.62;
            context.strokeStyle = colors[index % colors.length];
            context.stroke();
            start += slice;
        });
    }

    function renderCharts(data) {
        const growth = data.user_growth || [];
        const categories = data.redemptions_by_category || [];
        const statuses = data.voucher_status || [];
        const doughnutColors = [green, blue, yellow, purple, "#ef4444"];

        const growthCanvas = document.getElementById("userGrowthChart");
        const barCanvas = document.getElementById("categoryChart");
        const donutCanvas = document.getElementById("statusChart");

        if (!window.Chart) {
            drawFallbackLine(growthCanvas, growth);
            drawFallbackBars(barCanvas, categories);
            drawFallbackDonut(donutCanvas, statuses);
            renderStatusLegend(statuses, doughnutColors);
            return;
        }

        Chart.defaults.font.family = "Inter, Segoe UI, Arial, sans-serif";
        Chart.defaults.color = labelColor;

        if (growthCanvas) {
            if (charts.growth) {
                charts.growth.data.labels = growth.map((point) => point.date);
                charts.growth.data.datasets[0].data = growth.map((point) => point.users);
                charts.growth.update("none");
            } else {
                const gradient = growthCanvas.getContext("2d").createLinearGradient(0, 0, 0, 240);
                gradient.addColorStop(0, "rgba(255, 106, 0, 0.36)");
                gradient.addColorStop(1, "rgba(255, 106, 0, 0.02)");
                charts.growth = new Chart(growthCanvas, {
                    type: "line",
                    data: {
                        labels: growth.map((point) => point.date),
                        datasets: [{
                            label: "Total Users",
                            data: growth.map((point) => point.users),
                            borderColor: orange,
                            backgroundColor: gradient,
                            pointBackgroundColor: orange,
                            pointBorderColor: "#0f141b",
                            pointBorderWidth: 3,
                            pointRadius: (context) => context.dataIndex === growth.length - 1 ? 6 : 0,
                            tension: 0.36,
                            fill: true,
                        }],
                    },
                    options: chartOptions({
                        scales: {
                            x: { grid: { display: false }, ticks: { color: labelColor, maxTicksLimit: 7 }, border: { color: gridColor } },
                            y: {
                                grid: { color: gridColor, borderDash: [4, 4] },
                                ticks: {
                                    color: labelColor,
                                    callback: (value) => formatNumber(value),
                                },
                                border: { color: gridColor },
                            },
                        },
                    }),
                });
            }
        }

        if (barCanvas) {
            if (charts.category) {
                charts.category.data.labels = categories.map((row) => row.category);
                charts.category.data.datasets[0].data = categories.map((row) => row.redemptions);
                charts.category.data.datasets[0].backgroundColor = categories.map((_, index) => index === 0 ? "#ff9b3d" : orange);
                charts.category.update("none");
            } else {
                charts.category = new Chart(barCanvas, {
                    type: "bar",
                    data: {
                        labels: categories.map((row) => row.category),
                        datasets: [{
                            data: categories.map((row) => row.redemptions),
                            backgroundColor: categories.map((_, index) => index === 0 ? "#ff9b3d" : orange),
                            borderRadius: 4,
                            maxBarThickness: 34,
                        }],
                    },
                    options: chartOptions({
                        scales: {
                            x: {
                                grid: { display: false },
                                ticks: {
                                    color: labelColor,
                                    font: { size: 11 },
                                    maxRotation: 24,
                                    minRotation: 0,
                                    autoSkip: false,
                                },
                                border: { color: gridColor },
                            },
                            y: { grid: { color: gridColor }, ticks: { color: labelColor }, border: { color: gridColor } },
                        },
                    }),
                });
            }
        }

        if (donutCanvas) {
            if (charts.status) {
                charts.status.data.labels = statuses.map((row) => row.status);
                charts.status.data.datasets[0].data = statuses.map((row) => row.count);
                charts.status.update("none");
            } else {
                charts.status = new Chart(donutCanvas, {
                    type: "doughnut",
                    data: {
                        labels: statuses.map((row) => row.status),
                        datasets: [{
                            data: statuses.map((row) => row.count),
                            backgroundColor: doughnutColors,
                            borderWidth: 0,
                            hoverOffset: 4,
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        cutout: "62%",
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                backgroundColor: "rgba(15, 20, 27, 0.95)",
                                titleColor: "#fff",
                                bodyColor: "#dfe5ef",
                                borderColor: "rgba(255,255,255,0.12)",
                                borderWidth: 1,
                                padding: 12,
                            },
                        },
                    },
                });
            }
        }
        renderStatusLegend(statuses, doughnutColors);
    }

    function renderStatusLegend(statuses, colors) {
        const legend = document.getElementById("statusLegend");
        const total = (statuses || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
        setText("[data-status-total]", formatNumber(total));
        if (!legend) {
            return;
        }
        legend.innerHTML = "";
        statuses.forEach((row, index) => {
            const percent = total ? Math.round((Number(row.count || 0) / total) * 1000) / 10 : 0;
            const item = document.createElement("div");
            item.className = "legend-item";
            item.innerHTML = `
                <span class="legend-dot" style="background:${colors[index % colors.length]}"></span>
                <span>${row.status}</span>
                <span>${formatNumber(row.count)} (${percent}%)</span>
            `;
            legend.appendChild(item);
        });
    }

    async function loadDashboard(renderFallback = false) {
        if (dashboardRequestInFlight) {
            dashboardRefreshQueued = true;
            return;
        }
        const requestedDays = dashboardRangeDays;
        const fallback = window.__dashboardFallback__ || {};
        if (renderFallback && Object.keys(fallback).length && Number(fallback.range_days || 7) === requestedDays) {
            renderDashboard(fallback);
        }
        dashboardRequestInFlight = true;
        try {
            const response = await fetch(`/api/admin/dashboard-summary?days=${requestedDays}`, {
                credentials: "same-origin",
                cache: "no-store",
            });
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            if (requestedDays === dashboardRangeDays) {
                renderDashboard(data);
            }
        } catch (error) {
            if (renderFallback && Object.keys(fallback).length && Number(fallback.range_days || 7) === requestedDays) {
                renderDashboard(fallback);
            }
        } finally {
            dashboardRequestInFlight = false;
            if (dashboardRefreshQueued) {
                dashboardRefreshQueued = false;
                loadDashboard();
            }
        }
    }

    function startDashboardAutoRefresh() {
        loadDashboard(true);
        setInterval(() => {
            if (!document.hidden) {
                loadDashboard();
            }
        }, dashboardRefreshMs);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) {
                loadDashboard();
            }
        });
    }

    function renderDashboard(data) {
        renderKpis(data);
        renderCharts(data);
        renderRecentActivity(data.recent_merchant_activity || data.recent_activity);
        renderFlaggedVouchers(data.ai_flagged_vouchers);
        renderInsight(data);
        renderSystemStatus(data);
    }

    updateSearch();
    initDateRangePicker();
    initTopbarMenus();
    initVoucherFilters();
    initAnnouncementPreview();
    initAdminSettings();
    initAdminLiveSupport();
    if (page === "dashboard") {
        startDashboardAutoRefresh();
    }
})();
