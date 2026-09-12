(function () {
  "use strict";

  function addYearPicker(index) {
    const calendar = window.DateTimeShortcuts.calendars[index];
    const calendarBox = document.getElementById(`calendarbox${index}`);
    const caption = calendarBox && calendarBox.querySelector(".calendar caption");
    if (!calendar || !caption) return;

    const monthLabel = caption.textContent.trim().replace(/\s+\d{4}$/, "");
    const wrapper = document.createElement("span");
    wrapper.className = "calendar-caption-content";

    const month = document.createElement("span");
    month.className = "calendar-caption-month";
    month.textContent = monthLabel;

    let yearToolbar = calendarBox.querySelector(".calendar-year-toolbar");
    if (!yearToolbar) {
      yearToolbar = document.createElement("div");
      yearToolbar.className = "calendar-year-toolbar";
      calendarBox.insertBefore(yearToolbar, calendarBox.querySelector(".calendar"));
    }
    yearToolbar.replaceChildren();

    const yearLabel = document.createElement("span");
    yearLabel.className = "calendar-year-label";
    yearLabel.textContent = "ปี";

    const select = document.createElement("select");
    select.className = "calendar-year-picker";
    select.setAttribute("aria-label", "Select year");
    const currentYear = new Date().getFullYear();
    const firstYear = Math.min(1900, calendar.currentYear - 120);
    const lastYear = Math.max(currentYear + 10, calendar.currentYear + 10);

    for (let year = lastYear; year >= firstYear; year--) {
      const option = document.createElement("option");
      option.value = year;
      option.textContent = year;
      option.selected = year === calendar.currentYear;
      select.appendChild(option);
    }

    select.addEventListener("change", function () {
      calendar.drawDate(calendar.currentMonth, Number(select.value), calendar.selected);
    });

    yearToolbar.append(yearLabel, select);

    const previous = calendarBox.querySelector(".calendarnav-previous");
    const next = calendarBox.querySelector(".calendarnav-next");
    if (previous) {
      previous.classList.add("calendar-nav-source");
    }
    if (next) {
      next.classList.add("calendar-nav-source");
    }

    [
      ["previous", "\u2190", "Previous month", "drawPrev"],
      ["next", "\u2192", "Next month", "drawNext"],
    ].forEach(function ([direction, icon, label, action]) {
      if (calendarBox.querySelector(`[data-calendar-navigation="${direction}"]`)) return;

      const button = document.createElement("button");
      button.type = "button";
      button.className = `calendar-nav-button calendar-nav-button--${direction}`;
      button.dataset.calendarNavigation = direction;
      button.textContent = icon;
      button.setAttribute("aria-label", label);
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        window.DateTimeShortcuts[action](index);
      });
      calendarBox.appendChild(button);
    });

    wrapper.replaceChildren(
      calendarBox.querySelector('[data-calendar-navigation="previous"]'),
      month,
      calendarBox.querySelector('[data-calendar-navigation="next"]')
    );
    caption.replaceChildren(wrapper);
  }

  function enableYearPickers() {
    if (!window.DateTimeShortcuts) return;

    window.DateTimeShortcuts.calendars.forEach(function (calendar, index) {
      if (calendar.yearPickerEnabled) return;
      const drawCurrent = calendar.drawCurrent;
      calendar.drawCurrent = function () {
        drawCurrent.call(this);
        addYearPicker(index);
      };
      calendar.yearPickerEnabled = true;
      addYearPicker(index);
    });
  }

  window.addEventListener("load", function () {
    window.setTimeout(enableYearPickers, 0);
  });
})();
