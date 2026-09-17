/* Progressive enhancements; the original text and native audio work without JS. */
(() => {
  "use strict";
  const menu = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("#primary-nav");
  function closeMenu() {
    nav?.classList.remove("open");
    menu?.setAttribute("aria-expanded", "false");
  }
  menu?.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    menu.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && menu?.getAttribute("aria-expanded") === "true") {
      closeMenu();
      menu.focus();
    }
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".site-header")) closeMenu();
  });
  matchMedia("(min-width: 851px)").addEventListener("change", closeMenu);

  const today = new Date();
  const mmdd =
    String(today.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(today.getDate()).padStart(2, "0");
  document.querySelectorAll("[data-today]").forEach((a) => {
    a.href = "/reader/" + mmdd + "/";
  });

  const search = document.querySelector("[data-archive-search]");
  const month = document.querySelector("[data-archive-month]");
  const normalise = (text) =>
    text
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/\bst\.?\b/g, "saint")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  function filter() {
    if (!search) return;
    const terms = normalise(search.value).split(" ").filter(Boolean);
    let count = 0;
    document.querySelectorAll("[data-ep-card]").forEach((card) => {
      const haystack = normalise(card.dataset.q);
      const show =
        (!month.value || card.dataset.month === month.value) &&
        terms.every((term) => haystack.includes(term));
      card.hidden = !show;
      if (show) count++;
    });
    document.querySelector("[data-archive-count]").textContent =
      count + (count === 1 ? " episode" : " episodes");
    document.querySelector("[data-empty]").hidden = count !== 0;
  }
  search?.addEventListener("input", filter);
  month?.addEventListener("change", filter);
  document.querySelector("[data-reset]")?.addEventListener("click", () => {
    search.value = "";
    month.value = "";
    filter();
    search.focus();
  });

  const audioElements = [...document.querySelectorAll("audio")];
  const time = (seconds) => {
    const s = Number.isFinite(seconds) ? Math.floor(seconds) : 0;
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  };
  document.querySelectorAll("[data-player]").forEach((player) => {
    const audio = player.querySelector("audio");
    const play = player.querySelector("[data-play]");
    const seek = player.querySelector("[data-seek]");
    const speed = player.querySelector("[data-speed]");
    const error = player.querySelector("[data-player-error]");
    const label = player.querySelector("[data-player-label]");
    player.querySelector(".player-controls").hidden = false;
    audio.hidden = true;
    const update = () => {
      play.dataset.playing = String(!audio.paused);
      play.setAttribute(
        "aria-label",
        audio.paused ? "Play reading" : "Pause reading",
      );
      label.textContent = audio.paused
        ? "Listen to the full reading"
        : "Now playing";
      player.querySelector("[data-time]").textContent = time(audio.currentTime);
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        player.querySelector("[data-duration]").textContent = time(
          audio.duration,
        );
        seek.value = String((audio.currentTime / audio.duration) * 100);
        seek.setAttribute(
          "aria-valuetext",
          time(audio.currentTime) + " of " + time(audio.duration),
        );
      }
    };
    play.addEventListener("click", async () => {
      if (!audio.paused) {
        audio.pause();
        return;
      }
      audioElements.forEach((other) => {
        if (other !== audio) other.pause();
      });
      error.hidden = true;
      label.textContent = "Loading the reading…";
      try {
        await audio.play();
      } catch {
        error.hidden = false;
        update();
      }
    });
    ["play", "pause", "ended", "timeupdate", "loadedmetadata"].forEach(
      (event) => audio.addEventListener(event, update),
    );
    audio.addEventListener("error", () => {
      error.hidden = false;
      update();
    });
    seek.addEventListener("input", () => {
      if (Number.isFinite(audio.duration)) {
        audio.currentTime = (Number(seek.value) / 100) * audio.duration;
        update();
      }
    });
    speed.addEventListener("click", () => {
      const rates = [1, 1.25, 1.5, 0.75];
      audio.playbackRate =
        rates[(rates.indexOf(audio.playbackRate) + 1) % rates.length];
      speed.textContent = audio.playbackRate + "×";
      speed.setAttribute(
        "aria-label",
        "Playback speed: " + audio.playbackRate + " times",
      );
    });
  });
  document.querySelectorAll("[data-video]").forEach((container) => {
    container.querySelector("a").addEventListener("click", (e) => {
      e.preventDefault();
      audioElements.forEach((audio) => audio.pause());
      const iframe = document.createElement("iframe");
      iframe.src =
        "https://www.youtube-nocookie.com/embed/" +
        encodeURIComponent(container.dataset.video) +
        "?autoplay=1&rel=0";
      iframe.title = container.dataset.title;
      iframe.allow =
        "autoplay; encrypted-media; picture-in-picture; fullscreen";
      iframe.allowFullscreen = true;
      container.replaceChildren(iframe);
      iframe.focus();
    });
  });

  const fontButtons = document.querySelectorAll("[data-font]");
  if (fontButtons.length) {
    let size = matchMedia("(max-width: 600px)").matches ? 17 : 18;
    try {
      const saved = Number(localStorage.getItem("butler-reading-size"));
      if (saved >= 16 && saved <= 24) size = saved;
    } catch {
      /* private browsing */
    }
    const setSize = () => {
      document.documentElement.style.setProperty("--reading-size", size + "px");
      fontButtons.forEach((button) => {
        button.disabled =
          button.dataset.font === "smaller" ? size <= 16 : size >= 24;
      });
    };
    fontButtons.forEach((button) =>
      button.addEventListener("click", () => {
        size = Math.max(
          16,
          Math.min(24, size + (button.dataset.font === "larger" ? 1 : -1)),
        );
        setSize();
        try {
          localStorage.setItem("butler-reading-size", size);
        } catch {
          /* private browsing */
        }
      }),
    );
    setSize();
  }
})();
