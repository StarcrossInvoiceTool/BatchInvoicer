/* Shared invoice-form logic used by both stage2 and stage3 pages.
 *
 * Provides: form population, row totals, drag-select, sorting,
 * pricing calculation, preview, back-button, collectFormData, showError.
 *
 * Pages that need grand-total recalculation (stage2) override
 * updateGrandTotal() after this script loads.
 */

let currentSessionId = null;
let currentInvoiceData = null;
let currentInvoiceItems = null;
let originalInvoiceItems = null;
let sortState = { order: [] };
let isDragging = false;
let dragStartIndex = null;
let dragStartChecked = null;
let mouseDownTime = null;
let mouseDownPosition = null;
let currentMousePosition = null;

function updateGrandTotal() {}

function formatOurRef(ref) {
    if (!ref) return '';
    const refStr = String(ref).trim();
    if (refStr.endsWith('.0')) {
        return refStr.slice(0, -2);
    }
    return refStr;
}

function formatMiles(miles) {
    if (!miles) return '0.0';
    const milesStr = String(miles).trim().toLowerCase();
    if (milesStr === 'nan' || milesStr === '' || milesStr === 'null' || milesStr === 'undefined') {
        return '0.0';
    }
    return milesStr;
}

function formatMilesForCalculation(miles) {
    if (!miles) return 0;
    const milesStr = String(miles).trim().toLowerCase();
    if (milesStr === 'nan' || milesStr === '' || milesStr === 'null' || milesStr === 'undefined') {
        return 0;
    }
    return parseFloat(milesStr) || 0;
}

function populateForm(data) {
    document.getElementById('patient-name').value = data.patient.name || '';
    document.getElementById('patient-address').value = data.patient.address || '';
    document.getElementById('patient-postcode').value = data.patient.postcode || '';
    document.getElementById('invoice-number').value = data.invoice.number || '';
    document.getElementById('invoice-date').value = data.invoice.date || '';
    document.getElementById('account-ref').value = data.invoice.account_ref || '';
    document.getElementById('ref').value = data.invoice.ref || '';
    document.getElementById('po-number').value = data.invoice.po_number || '';
    document.getElementById('payment-terms').value = data.invoice.payment_terms || '';
    document.getElementById('period').value = data.invoice.period || '';
    document.getElementById('net-label').value = data.financial.net_label || 'net';
    document.getElementById('net').value = data.financial.net || '';
    document.getElementById('discount-label').value = data.financial.discount_label || 'discount';
    document.getElementById('discount').value = data.financial.discount || '';
    document.getElementById('subtotal-label').value = data.financial.subtotal_label || 'Invoice subtotal';
    document.getElementById('subtotal').value = data.financial.subtotal || '';
    document.getElementById('vat-label').value = data.financial.vat_label || 'VAT';
    document.getElementById('vat-percentage').value = data.financial.vat_percentage || '20';
    document.getElementById('vat-amount').value = data.financial.vat_amount || '';
    document.getElementById('total-label').value = data.financial.total_label || 'TOTAL DUE';
    document.getElementById('total').value = data.financial.total || '';
    calculateSubtotalAndVAT();
    document.getElementById('bank-name').value = 'Lloyds Bank Plc';
    document.getElementById('bank-account-name').value = 'Starcross Trading Limited';
    document.getElementById('bank-account-number').value = '82082760';
    document.getElementById('bank-sort-code').value = '30-99-21';
    document.getElementById('paid-stamp-checkbox').checked = data.paid || false;
    const style = data.style || 'style1';
    if (style === 'style2') {
        document.getElementById('style2-radio').checked = true;
    } else {
        document.getElementById('style1-radio').checked = true;
    }
    toggleStyleOptions();
    document.getElementById('item-name-input').value = data.item_name || '';

    originalInvoiceItems = JSON.parse(JSON.stringify(data.invoice.items));
    currentInvoiceItems = data.invoice.items;

    sortState = { order: [] };
    updateSortIndicators();
    populateInvoiceItemsTable(currentInvoiceItems);
}

function updateRowTotal(index) {
    const waitInput = document.querySelector(`.item-wait-pounds[data-index="${index}"]`);
    const milesInput = document.querySelector(`.item-miles-pounds[data-index="${index}"]`);
    const jobInput = document.querySelector(`.item-job-pounds[data-index="${index}"]`);
    const totalInput = document.querySelector(`.item-total[data-index="${index}"]`);

    if (waitInput && milesInput && jobInput && totalInput) {
        const wait = parseFloat(waitInput.value) || 0;
        const miles = parseFloat(milesInput.value) || 0;
        const job = parseFloat(jobInput.value) || 0;
        const total = wait + miles + job;
        totalInput.value = total.toFixed(2);
    }

    updateGrandTotal();
}

function calculateSubtotalAndVAT() {
    const net = parseFloat(document.getElementById('net').value) || 0;
    const discount = parseFloat(document.getElementById('discount').value) || 0;
    const subtotal = net - discount;

    const subtotalField = document.getElementById('subtotal');
    if (subtotalField) {
        subtotalField.value = subtotal.toFixed(2);
    }

    calculateVAT();
}

function calculateVAT() {
    const subtotalField = document.getElementById('subtotal');
    const subtotal = parseFloat(subtotalField ? subtotalField.value : 0) || 0;

    const vatPercentage = parseFloat(document.getElementById('vat-percentage').value) || 0;
    const vatAmount = subtotal * (vatPercentage / 100);

    const vatAmountField = document.getElementById('vat-amount');
    if (vatAmountField) {
        vatAmountField.value = vatAmount.toFixed(2);
    }

    const total = subtotal + vatAmount;

    const totalField = document.getElementById('total');
    if (totalField) {
        totalField.value = total.toFixed(2);
    }
}

window.calculateSubtotalAndVAT = calculateSubtotalAndVAT;
window.calculateVAT = calculateVAT;

function populateInvoiceItemsTable(items) {
    const filteredItems = items.filter(item => {
        const dateIsNan = !item.date || item.date.toLowerCase() === 'nan' || item.date.trim() === '';
        const refIsNan = !item.our_ref || item.our_ref.toLowerCase() === 'nan' || item.our_ref.trim() === '';
        return !(dateIsNan && refIsNan);
    });

    currentInvoiceItems = filteredItems;

    const tbody = document.getElementById('invoice-items-table');
    tbody.innerHTML = '';

    filteredItems.forEach((item, index) => {
        const row = document.createElement('tr');
        row.className = 'border-b hover:bg-gray-50';
        row.id = `invoice-row-${index}`;
        row.setAttribute('data-index', index);

        row.addEventListener('mousedown', (e) => {
            if (e.target.type === 'checkbox') return;
            mouseDownTime = Date.now();
            mouseDownPosition = { x: e.clientX, y: e.clientY };
            const checkbox = row.querySelector('.item-checkbox');
            if (checkbox) {
                dragStartIndex = index;
                dragStartChecked = !checkbox.checked;
            }
        });

        row.addEventListener('mousemove', (e) => {
            currentMousePosition = { x: e.clientX, y: e.clientY };
        });

        row.addEventListener('mouseenter', (e) => {
            currentMousePosition = { x: e.clientX, y: e.clientY };

            if (mouseDownTime !== null && dragStartIndex !== null && !isDragging) {
                const timeSinceMouseDown = Date.now() - mouseDownTime;
                const distance = mouseDownPosition && currentMousePosition ?
                    Math.sqrt(Math.pow(currentMousePosition.x - mouseDownPosition.x, 2) +
                             Math.pow(currentMousePosition.y - mouseDownPosition.y, 2)) : 0;

                if (distance > 5 || timeSinceMouseDown > 100) {
                    isDragging = true;
                    const checkbox = document.querySelector(`.item-checkbox[data-index="${dragStartIndex}"]`);
                    if (checkbox) {
                        checkbox.checked = dragStartChecked;
                        updateRowSelection(dragStartIndex, dragStartChecked);
                    }
                }
            }

            if (isDragging && dragStartIndex !== null) {
                const start = Math.min(dragStartIndex, index);
                const end = Math.max(dragStartIndex, index);
                for (let i = start; i <= end; i++) {
                    updateRowSelection(i, dragStartChecked);
                }
            }
        });

        row.innerHTML = `
            <td class="px-4 py-2">
                <input type="checkbox"
                       class="item-checkbox cursor-pointer"
                       data-index="${index}"
                       checked
                       onchange="updateSelectedCount(); updateGrandTotal();">
            </td>
            <td class="px-4 py-2 text-sm text-gray-700">${item.date || ''}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${formatOurRef(item.our_ref || '')}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${item.client_ref || ''}</td>
            <td class="px-4 py-2 text-sm text-gray-700 font-medium">${item.mob || ''}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${formatMiles(item.miles)}</td>
            <td class="px-4 py-2">
                <input type="number" step="0.01"
                       class="item-wait-pounds w-full border border-gray-300 rounded px-2 py-1 text-sm"
                       data-index="${index}"
                       value="${item.wait_pounds || ''}"
                       oninput="updateRowTotal(${index})">
            </td>
            <td class="px-4 py-2">
                <input type="number" step="0.01"
                       class="item-miles-pounds w-full border border-gray-300 rounded px-2 py-1 text-sm"
                       data-index="${index}"
                       value="${item.miles_pounds || ''}"
                       oninput="updateRowTotal(${index})">
            </td>
            <td class="px-4 py-2">
                <input type="number" step="0.01"
                       class="item-job-pounds w-full border border-gray-300 rounded px-2 py-1 text-sm"
                       data-index="${index}"
                       value="${item.job_pounds || ''}"
                       oninput="updateRowTotal(${index})">
            </td>
            <td class="px-4 py-2">
                <input type="number" step="0.01"
                       class="item-total w-full border border-gray-300 rounded px-2 py-1 text-sm font-semibold"
                       data-index="${index}"
                       data-actual-mileage="${formatMilesForCalculation(item.miles)}"
                       value="${item.total || ''}">
            </td>
        `;
        tbody.appendChild(row);
    });

    window.updateRowTotal = updateRowTotal;
    window.updateGrandTotal = updateGrandTotal;

    updateSelectedCount();
    updateGrandTotal();
}

if (!window.dragListenerAdded) {
    document.addEventListener('mouseup', stopDragging);
    document.addEventListener('mousemove', (e) => {
        currentMousePosition = { x: e.clientX, y: e.clientY };
    });
    window.dragListenerAdded = true;
}

function updateRowSelection(index, checked) {
    const checkbox = document.querySelector(`.item-checkbox[data-index="${index}"]`);
    const row = document.getElementById(`invoice-row-${index}`);

    if (checkbox) {
        checkbox.checked = checked;
    }

    if (row) {
        if (checked) {
            row.classList.add('bg-blue-50');
        } else {
            row.classList.remove('bg-blue-50');
        }
    }

    updateGrandTotal();
}

function stopDragging() {
    if (mouseDownTime !== null && !isDragging && dragStartIndex !== null) {
        const timeSinceMouseDown = Date.now() - mouseDownTime;
        const distance = mouseDownPosition && currentMousePosition ?
            Math.sqrt(Math.pow(currentMousePosition.x - mouseDownPosition.x, 2) +
                     Math.pow(currentMousePosition.y - mouseDownPosition.y, 2)) : 0;

        if (timeSinceMouseDown < 300 && distance < 10) {
            const checkbox = document.querySelector(`.item-checkbox[data-index="${dragStartIndex}"]`);
            if (checkbox) {
                checkbox.checked = dragStartChecked;
                updateRowSelection(dragStartIndex, dragStartChecked);
                updateSelectedCount();
            }
        }
    }

    if (isDragging) {
        updateSelectedCount();
    }

    isDragging = false;
    dragStartIndex = null;
    dragStartChecked = null;
    mouseDownTime = null;
    mouseDownPosition = null;
    currentMousePosition = null;
}

window.sortTable = function(column) {
    if (!originalInvoiceItems || originalInvoiceItems.length === 0) return;

    const existingIndex = sortState.order.findIndex(s => s.column === column);

    if (existingIndex >= 0) {
        const currentSort = sortState.order[existingIndex];
        if (currentSort.direction === 'asc') {
            sortState.order[existingIndex].direction = 'desc';
        } else {
            sortState.order.splice(existingIndex, 1);
        }
    } else {
        sortState.order.push({ column: column, direction: 'asc' });
    }

    const sortedItems = JSON.parse(JSON.stringify(originalInvoiceItems));

    sortedItems.sort((a, b) => {
        for (let i = 0; i < sortState.order.length; i++) {
            const sortCriteria = sortState.order[i];
            const col = sortCriteria.column;
            const direction = sortCriteria.direction;

            let aVal, bVal;

            if (col === 'date') {
                aVal = a.date ? new Date(a.date) : new Date(0);
                bVal = b.date ? new Date(b.date) : new Date(0);
            } else if (col === 'mob') {
                aVal = (a.mob || '').toLowerCase();
                bVal = (b.mob || '').toLowerCase();
            } else if (col === 'miles') {
                aVal = formatMilesForCalculation(a.miles);
                bVal = formatMilesForCalculation(b.miles);
            } else {
                continue;
            }

            if (aVal < bVal) return direction === 'asc' ? -1 : 1;
            if (aVal > bVal) return direction === 'asc' ? 1 : -1;
        }
        return 0;
    });

    updateSortIndicators();
    populateInvoiceItemsTable(sortedItems);
};

function updateSortIndicators() {
    document.getElementById('sort-date-indicator').textContent = '';
    document.getElementById('sort-mob-indicator').textContent = '';
    document.getElementById('sort-miles-indicator').textContent = '';

    sortState.order.forEach((sortCriteria, index) => {
        const indicator = sortCriteria.direction === 'asc' ? '\u2191' : '\u2193';
        const orderNumber = sortState.order.length > 1 ? `${index + 1}` : '';
        const fullIndicator = orderNumber + indicator;

        if (sortCriteria.column === 'date') {
            document.getElementById('sort-date-indicator').textContent = fullIndicator;
        } else if (sortCriteria.column === 'mob') {
            document.getElementById('sort-mob-indicator').textContent = fullIndicator;
        } else if (sortCriteria.column === 'miles') {
            document.getElementById('sort-miles-indicator').textContent = fullIndicator;
        }
    });
}

window.toggleSelectAll = function() {
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const itemCheckboxes = document.querySelectorAll('.item-checkbox');
    const isChecked = selectAllCheckbox.checked;

    itemCheckboxes.forEach(checkbox => {
        checkbox.checked = isChecked;
        const row = document.getElementById(`invoice-row-${checkbox.getAttribute('data-index')}`);
        if (row) {
            if (isChecked) {
                row.classList.add('bg-blue-50');
            } else {
                row.classList.remove('bg-blue-50');
            }
        }
    });

    updateSelectedCount();
    updateGrandTotal();
};

window.updateSelectedCount = function() {
    const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
    const count = selectedCheckboxes.length;
    const countElement = document.getElementById('selected-count');

    if (countElement) {
        countElement.textContent = `${count} item${count !== 1 ? 's' : ''} selected`;
    }

    document.querySelectorAll('.item-checkbox').forEach(checkbox => {
        const index = checkbox.getAttribute('data-index');
        const row = document.getElementById(`invoice-row-${index}`);

        if (row) {
            if (checkbox.checked) {
                row.classList.add('bg-blue-50');
            } else {
                row.classList.remove('bg-blue-50');
            }
        }
    });

    const allCheckboxes = document.querySelectorAll('.item-checkbox');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    if (selectAllCheckbox && allCheckboxes.length > 0) {
        const allChecked = Array.from(allCheckboxes).every(cb => cb.checked);
        const someChecked = Array.from(allCheckboxes).some(cb => cb.checked);
        selectAllCheckbox.checked = allChecked;
        selectAllCheckbox.indeterminate = someChecked && !allChecked;
    }
};

window.calculateSelectedTotals = function() {
    const jobPrice = parseFloat(document.getElementById('job-price-flat').value) || 0;
    const mileageIncluded = parseFloat(document.getElementById('mileage-included').value) || 0;
    const mileageCharge = parseFloat(document.getElementById('mileage-charge').value) || 0;

    if (!jobPrice) {
        alert('Please enter a Job Price (Flat) first');
        return;
    }

    const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');

    if (selectedCheckboxes.length === 0) {
        alert('Please select at least one item to calculate');
        return;
    }

    selectedCheckboxes.forEach(checkbox => {
        const index = checkbox.getAttribute('data-index');

        const jobPoundsInput = document.querySelector(`.item-job-pounds[data-index="${index}"]`);
        if (jobPoundsInput) {
            jobPoundsInput.value = jobPrice.toFixed(2);
        }

        const totalInput = document.querySelector(`.item-total[data-index="${index}"]`);
        if (!totalInput) return;

        const actualMileage = parseFloat(totalInput.getAttribute('data-actual-mileage')) || 0;

        let milesChargeAmount = 0;
        let extraMilesRounded = 0;
        if (actualMileage > mileageIncluded) {
            const extraMiles = actualMileage - mileageIncluded;
            extraMilesRounded = Math.ceil(extraMiles);
            milesChargeAmount = extraMilesRounded * mileageCharge;
        }

        const milesPoundsInput = document.querySelector(`.item-miles-pounds[data-index="${index}"]`);
        if (milesPoundsInput) {
            milesPoundsInput.value = milesChargeAmount.toFixed(2);
        }

        if (currentInvoiceItems && currentInvoiceItems[index]) {
            currentInvoiceItems[index].charged = extraMilesRounded > 0 ? extraMilesRounded.toString() : '0';
        }

        updateRowTotal(index);
    });
};

function showError(message) {
    const errorDiv = document.getElementById('error');
    errorDiv.querySelector('p').textContent = message;
    errorDiv.classList.remove('hidden');
}

function toggleStyleOptions() {
    const style2Radio = document.getElementById('style2-radio');
    const style2Options = document.getElementById('style2-options');
    if (style2Radio.checked) {
        style2Options.classList.remove('hidden');
    } else {
        style2Options.classList.add('hidden');
    }
}

window.toggleStyleOptions = toggleStyleOptions;

function collectFormData() {
    const updatedItems = currentInvoiceItems
        .map((item, index) => {
            const checkbox = document.querySelector(`.item-checkbox[data-index="${index}"]`);
            const isSelected = checkbox ? checkbox.checked : false;

            if (!isSelected) return null;

            const waitPoundsInput = document.querySelector(`.item-wait-pounds[data-index="${index}"]`);
            const milesPoundsInput = document.querySelector(`.item-miles-pounds[data-index="${index}"]`);
            const jobPoundsInput = document.querySelector(`.item-job-pounds[data-index="${index}"]`);
            const totalInput = document.querySelector(`.item-total[data-index="${index}"]`);

            return {
                ...item,
                wait_pounds: waitPoundsInput ? waitPoundsInput.value : item.wait_pounds,
                miles_pounds: milesPoundsInput ? milesPoundsInput.value : item.miles_pounds,
                job_pounds: jobPoundsInput ? jobPoundsInput.value : item.job_pounds,
                total: totalInput ? totalInput.value : item.total,
                charged: item.charged || '0'
            };
        })
        .filter(item => item !== null);

    const selectedStyle = document.querySelector('input[name="invoice-style"]:checked').value;
    let calculatedTotal = document.getElementById('total').value;

    if (selectedStyle === 'style1') {
        let sum = 0;
        updatedItems.forEach(item => {
            const itemTotal = parseFloat(item.total) || 0;
            if (itemTotal > 0) {
                sum += itemTotal;
            }
        });
        calculatedTotal = sum.toFixed(2);
    } else if (selectedStyle === 'style2') {
        const totalField = document.getElementById('total');
        calculatedTotal = totalField ? totalField.value : '0.00';
    }

    const result = {
        patient: {
            name: document.getElementById('patient-name').value,
            address: document.getElementById('patient-address').value,
            postcode: document.getElementById('patient-postcode').value
        },
        invoice: {
            ...currentInvoiceData.invoice,
            number: document.getElementById('invoice-number').value,
            date: document.getElementById('invoice-date').value,
            account_ref: document.getElementById('account-ref').value,
            ref: document.getElementById('ref').value,
            po_number: document.getElementById('po-number').value,
            payment_terms: document.getElementById('payment-terms').value,
            period: document.getElementById('period').value,
            items: updatedItems
        },
        financial: {
            net: document.getElementById('net').value,
            net_label: document.getElementById('net-label').value,
            discount: document.getElementById('discount').value,
            discount_label: document.getElementById('discount-label').value,
            subtotal: document.getElementById('subtotal').value,
            subtotal_label: document.getElementById('subtotal-label').value,
            vat_amount: document.getElementById('vat-amount').value,
            vat_label: document.getElementById('vat-label').value,
            vat_percentage: document.getElementById('vat-percentage').value,
            total: calculatedTotal,
            total_label: document.getElementById('total-label').value
        },
        bank: {
            name: 'Lloyds Bank Plc',
            account_name: 'Starcross Trading Limited',
            account_number: '82082760',
            sort_code: '30-99-21'
        },
        paid: document.getElementById('paid-stamp-checkbox').checked,
        style: selectedStyle,
        item_name: document.getElementById('item-name-input').value
    };

    const jobPriceFlatEl = document.getElementById('job-price-flat');
    const mileageIncludedEl = document.getElementById('mileage-included');
    const mileageChargeEl = document.getElementById('mileage-charge');
    if (jobPriceFlatEl && mileageIncludedEl && mileageChargeEl) {
        result.pricing = {
            job_price_flat: jobPriceFlatEl.value || '',
            mileage_included: mileageIncludedEl.value || '',
            mileage_charge: mileageChargeEl.value || ''
        };
    }

    return result;
}

document.getElementById('preview-btn').addEventListener('click', async () => {
    if (!currentSessionId) return;

    const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
    if (selectedCheckboxes.length === 0) {
        showError('Please select at least one line item to preview');
        return;
    }

    const formData = collectFormData();
    const formDataToSend = new FormData();
    formDataToSend.append('session_id', currentSessionId);
    formDataToSend.append('invoice_data_json', JSON.stringify(formData));
    formDataToSend.append('preview', 'true');

    try {
        const response = await fetch('/api/update-invoice', {
            method: 'POST',
            body: formDataToSend
        });

        if (!response.ok) throw new Error('Preview failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        window.open(url, '_blank');
        window.URL.revokeObjectURL(url);
    } catch (error) {
        showError('Failed to generate preview');
    }
});

(function() {
    const backToPreviousBtn = document.getElementById('back-to-previous-btn');
    if (!backToPreviousBtn) return;

    const previousPageData = sessionStorage.getItem('previousPage');

    if (previousPageData) {
        try {
            const data = JSON.parse(previousPageData);
            backToPreviousBtn.href = data.url;
            backToPreviousBtn.classList.remove('hidden');

            backToPreviousBtn.addEventListener('click', (e) => {
                e.preventDefault();
                if (data.state) {
                    sessionStorage.setItem('restoreState', JSON.stringify(data.state));
                }
                window.location.href = data.url;
            });
        } catch (e) {
            console.error('Failed to parse previous page data:', e);
            backToPreviousBtn.href = '/';
            backToPreviousBtn.classList.remove('hidden');
        }
    } else {
        backToPreviousBtn.href = '/';
        backToPreviousBtn.classList.remove('hidden');
    }
})();
