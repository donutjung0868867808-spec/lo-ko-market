(function () {
  function setupImagePicker(input) {
    if (input.dataset.categoryPickerReady) return;
    input.dataset.categoryPickerReady = "true";

    var picker = document.createElement("button");
    var icon = document.createElement("span");
    var copy = document.createElement("span");
    var title = document.createElement("strong");
    var hint = document.createElement("small");
    var preview = document.createElement("img");
    var previewUrl = "";

    picker.type = "button";
    picker.className = "category-image-picker";
    icon.className = "category-image-picker-icon";
    icon.textContent = "+";
    title.textContent = "เลือกรูปหมวดสินค้า";
    hint.textContent = "กดเลือกไฟล์ หรือลากรูปมาวางได้ ชื่อไฟล์ไม่จำเป็นต้องมีนามสกุล";
    copy.append(title, hint);
    picker.append(icon, copy);
    preview.className = "category-image-preview";
    preview.alt = "ตัวอย่างรูปหมวดสินค้า";
    preview.hidden = true;

    input.classList.add("category-image-input");
    input.insertAdjacentElement("beforebegin", preview);
    input.insertAdjacentElement("beforebegin", picker);

    function showPreview(file) {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      if (!file) {
        preview.hidden = true;
        preview.removeAttribute("src");
        return;
      }
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
      preview.hidden = false;
    }

    function useFile(file) {
      if (!file) return;
      var transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      showPreview(file);
    }

    picker.addEventListener("click", function () {
      input.click();
    });
    input.addEventListener("change", function () {
      showPreview(input.files && input.files[0]);
    });
    picker.addEventListener("dragover", function (event) {
      event.preventDefault();
      picker.classList.add("is-dragging");
    });
    picker.addEventListener("dragleave", function () {
      picker.classList.remove("is-dragging");
    });
    picker.addEventListener("drop", function (event) {
      event.preventDefault();
      picker.classList.remove("is-dragging");
      useFile(event.dataTransfer.files[0]);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-category-image-input]").forEach(setupImagePicker);
  });
}());
