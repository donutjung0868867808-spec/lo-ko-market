(function () {
  function openBannerCropper(file, aspect, onSave, onCancel) {
    var outputWidth = 1300;
    var outputHeight = Math.round(outputWidth / aspect);
    var modal = document.createElement("div");
    var dialog = document.createElement("section");
    var heading = document.createElement("h2");
    var hint = document.createElement("p");
    var canvas = document.createElement("canvas");
    var actions = document.createElement("div");
    var cancel = document.createElement("button");
    var save = document.createElement("button");
    var context = canvas.getContext("2d");
    var image = new Image();
    var imageUrl = URL.createObjectURL(file);
    var baseScale = 1;
    var scale = 1;
    var offsetX = 0;
    var offsetY = 0;
    var dragging = null;

    modal.className = "admin-image-cropper";
    dialog.className = "admin-image-cropper__dialog";
    heading.textContent = "จัดตำแหน่งภาพสไลด์";
    hint.textContent = "ลากภาพ หรือเลื่อนล้อเมาส์บนภาพเพื่อซูมและดูภาพจริงในกรอบหน้าแรก";
    canvas.className = "admin-image-cropper__canvas";
    canvas.width = outputWidth;
    canvas.height = outputHeight;
    canvas.setAttribute("aria-label", "ตัวอย่างภาพสไลด์หน้าแรก");
    actions.className = "admin-image-cropper__actions";
    cancel.type = "button";
    cancel.className = "button";
    cancel.textContent = "ยกเลิก";
    save.type = "button";
    save.className = "button default";
    save.textContent = "ใช้รูปนี้";
    actions.append(cancel, save);
    dialog.append(heading, hint, canvas, actions);
    modal.appendChild(dialog);
    document.body.appendChild(modal);
    document.body.classList.add("admin-image-cropper-open");

    function close() {
      URL.revokeObjectURL(imageUrl);
      modal.remove();
      document.body.classList.remove("admin-image-cropper-open");
    }

    function constrainPosition() {
      var imageWidth = image.naturalWidth * scale;
      var imageHeight = image.naturalHeight * scale;
      offsetX = Math.min(0, Math.max(canvas.width - imageWidth, offsetX));
      offsetY = Math.min(0, Math.max(canvas.height - imageHeight, offsetY));
    }

    function render() {
      if (!image.naturalWidth) return;
      constrainPosition();
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(
        image,
        offsetX,
        offsetY,
        image.naturalWidth * scale,
        image.naturalHeight * scale
      );
    }

    function pointFor(event) {
      var bounds = canvas.getBoundingClientRect();
      return {
        x: (event.clientX - bounds.left) * (canvas.width / bounds.width),
        y: (event.clientY - bounds.top) * (canvas.width / bounds.width)
      };
    }

    function zoomTo(nextScale, point) {
      var limitedScale = Math.max(baseScale, Math.min(baseScale * 3, nextScale));
      var focus = point || { x: canvas.width / 2, y: canvas.height / 2 };
      var ratio = limitedScale / scale;
      offsetX = focus.x - (focus.x - offsetX) * ratio;
      offsetY = focus.y - (focus.y - offsetY) * ratio;
      scale = limitedScale;
      render();
    }

    image.onload = function () {
      baseScale = Math.max(canvas.width / image.naturalWidth, canvas.height / image.naturalHeight);
      scale = baseScale;
      offsetX = (canvas.width - image.naturalWidth * scale) / 2;
      offsetY = (canvas.height - image.naturalHeight * scale) / 2;
      render();
    };
    image.src = imageUrl;

    canvas.addEventListener("wheel", function (event) {
      event.preventDefault();
      zoomTo(scale * (event.deltaY < 0 ? 1.1 : 1 / 1.1), pointFor(event));
    }, { passive: false });
    canvas.addEventListener("pointerdown", function (event) {
      canvas.setPointerCapture(event.pointerId);
      dragging = {
        x: event.clientX,
        y: event.clientY,
        offsetX: offsetX,
        offsetY: offsetY
      };
    });
    canvas.addEventListener("pointermove", function (event) {
      if (!dragging) return;
      var ratio = canvas.width / canvas.getBoundingClientRect().width;
      offsetX = dragging.offsetX + (event.clientX - dragging.x) * ratio;
      offsetY = dragging.offsetY + (event.clientY - dragging.y) * ratio;
      render();
    });
    canvas.addEventListener("pointerup", function () {
      dragging = null;
    });
    canvas.addEventListener("pointercancel", function () {
      dragging = null;
    });
    cancel.addEventListener("click", function () {
      close();
      onCancel();
    });
    save.addEventListener("click", function () {
      canvas.toBlob(function (blob) {
        if (!blob) return;
        var croppedFile = new File(
          [blob],
          file.name.replace(/\.[^.]+$/, "") + "-slide.jpg",
          { type: "image/jpeg" }
        );
        close();
        onSave(croppedFile);
      }, "image/jpeg", 0.9);
    });
  }

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
    var cropAspect = Number(input.dataset.imageCropAspect || 0);

    picker.type = "button";
    picker.className = "category-image-picker";
    icon.className = "category-image-picker-icon";
    icon.textContent = "+";
    title.textContent = input.dataset.imagePickerTitle || "เลือกรูปภาพ";
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
      if (cropAspect) {
        openBannerCropper(
          file,
          cropAspect,
          function (croppedFile) {
            var croppedTransfer = new DataTransfer();
            croppedTransfer.items.add(croppedFile);
            input.files = croppedTransfer.files;
            showPreview(croppedFile);
          },
          function () {
            input.value = "";
            showPreview(null);
          }
        );
        return;
      }
      var transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      showPreview(file);
    }

    picker.addEventListener("click", function () {
      input.click();
    });
    input.addEventListener("change", function () {
      useFile(input.files && input.files[0]);
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
    document.querySelectorAll("[data-admin-image-input]").forEach(setupImagePicker);
  });
}());
