
BITS 16
ORG 0x7C00

start:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    mov [boot_drive], dl

    ; Enable A20 before any write/copy above the 1 MiB boundary.  The fast
    ; port-0x92 method is supported by the intended PC/QEMU targets and avoids
    ; the old 20-bit address wrap that would alias 0x100000 to low memory.
    in al, 0x92
    or al, 0x02
    and al, 0xFE
    out 0x92, al

    ; Load the raw freestanding kernel one 512-byte sector at a time.
    ; Destination starts at physical 0x10000. Maximum supported payload:
    ; 0x7E00 sectors (~16 MiB), although the normal first build is tiny.
    xor bx, bx
    mov word [load_segment], 0x1000
    mov word [current_lba], 1

.load_next:
    mov ax, [kernel_sectors]
    test ax, ax
    jz .loaded
    dec ax
    mov [kernel_sectors_left], ax

    mov ax, [load_segment]
    mov [dap_segment], ax
    mov word [dap_offset], 0

    ; LBA low 16 bits. The first kernel is deliberately kept small.
    xor eax, eax
    mov ax, [current_lba]
    mov [dap_lba_low], eax
    mov dword [dap_lba_high], 0

    mov si, dap
    mov dl, [boot_drive]
    mov ah, 0x42
    int 0x13
    jc disk_error

    inc word [current_lba]
    add word [load_segment], 0x20

    cmp word [kernel_sectors_left], 0
    jne .load_next

.loaded:
    ; Enter 32-bit protected mode.
    cli
    lgdt [gdt_descriptor]
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    jmp 0x08:protected_mode

disk_error:
    mov si, disk_error_msg
.print:
    lodsb
    test al, al
    jz .halt
    mov ah, 0x0E
    mov bh, 0
    int 0x10
    jmp .print
.halt:
    cli
    hlt
    jmp .halt

BITS 32
protected_mode:
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov esp, 0x90000

    ; Copy loaded kernel from 0x10000 -> 0x100000.
    movzx ecx, word [kernel_sectors]
    imul ecx, 128
    mov esi, 0x10000
    mov edi, 0x100000
    cld
    rep movsd

    ; Build identity mapping for the first 1 GiB using 2 MiB pages.
    ; PML4 at 0x9000, PDPT at 0xA000, PD at 0xB000.
    mov edi, 0x9000
    xor eax, eax
    mov ecx, 3072
    rep stosd

    mov dword [0x9000], 0xA003
    mov dword [0xA000], 0xB003

    ; PD entries: 512 x 2 MiB = 1 GiB.
    mov edi, 0xB000
    xor ebx, ebx
    mov ecx, 512
.make_pd:
    mov eax, ebx
    or eax, 0x083
    mov [edi], eax
    mov dword [edi+4], 0
    add ebx, 0x200000
    add edi, 8
    loop .make_pd

    ; Enable PAE.
    mov eax, cr4
    or eax, 1 << 5
    mov cr4, eax

    ; CR3 = PML4.
    mov eax, 0x9000
    mov cr3, eax

    ; Enable long mode through EFER.LME.
    mov ecx, 0xC0000080
    rdmsr
    or eax, 1 << 8
    wrmsr

    ; Enable paging.
    mov eax, cr0
    or eax, 1 << 31
    mov cr0, eax

    lgdt [gdt64_descriptor]
    jmp 0x08:long_mode

BITS 64
long_mode:
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov rsp, 0x80000

    ; Call the C kernel at the address recorded by the build step.  This is
    ; patched from the ELF symbol value, so the boot stub never relies on
    ; name mangling or on a function merely happening to be first in .text.
    mov rax, [kernel_entry_ptr]
    test rax, rax
    jz .entry_error
    call rax

.entry_error:
    cli
    hlt
    jmp .entry_error

.hang:
    cli
    hlt
    jmp .hang

boot_drive db 0
load_segment dw 0x1000
current_lba dw 1
; Build-time marker; patched to the real sector count before the image is written.
kernel_sectors dw 0x4B53
kernel_sectors_left dw 0

dap:
    db 0x10
    db 0
    dw 1
dap_offset dw 0
dap_segment dw 0x1000
dap_lba_low dd 1
dap_lba_high dd 0

; Magic marker + 64-bit entry address patched by the Python build step.
; The magic value is intentionally non-zero and unique for safe replacement.
kernel_entry_ptr:
    dq 0x564D4158454E5452

disk_error_msg db "VMAX Kernel: disk read error", 0

align 8
gdt_start:
    dq 0x0000000000000000
    ; 64-bit code: L=1, G=1, present, ring 0, executable/readable.
    dq 0x00AF9A000000FFFF
    ; Data segment: present, ring 0, writable. Long mode ignores the base/limit.
    dq 0x00CF92000000FFFF
gdt_end:

gdt_descriptor:
    dw gdt_end - gdt_start - 1
    dd gdt_start

gdt64_descriptor:
    dw gdt_end - gdt_start - 1
    dq gdt_start

times 510-($-$$) db 0
dw 0xAA55
