#include "bank.h"
#include <windows.h>
#include <iostream>
#include <stdexcept>
std::string input(const std::string& prompt) {
    std::cout << prompt << std::flush;
    std::string s; if (!std::getline(std::cin, s)) throw std::runtime_error("Input ended.");
    return s;
}
int main() {
    try {
        // Deny simultaneous instances, including different copies using the same working directory.
        HANDLE lock = CreateFileA("account.lock", GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                  OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (lock == INVALID_HANDLE_VALUE) throw std::runtime_error("Another instance holds the ledger lock.");
        struct LockCloser { HANDLE h; ~LockCloser() { CloseHandle(h); } } closer{lock};
        Bank bank("account.txt");
        std::string id;
        while (true) {
            id = input("Please input your account number: ");
            try {
                const auto& r = bank.get(id);
                if (input("Please input your account password: ") != r.password)
                    throw std::runtime_error("Wrong password.");
                break;
            } catch (const std::exception& e) {
                if (!std::cin) throw;
                std::cout << "Warning: " << e.what() << '\n';
            }
        }
        while (true) {
            auto op = input("1. Inquiry\n2. Deposit\n3. Withdraw\n4. Transfer\n5. Quit\nPlease select: ");
            if (op == "5") break;
            try {
                if (op != "1" && op != "2" && op != "3" && op != "4")
                    throw std::runtime_error("Choose 1 through 5.");
                std::string target; Money amount = 0;
                if (op == "4") { target = input("Target account: "); bank.get(target); }
                if (op != "1") amount = parseMoney(input("Amount: "));
                if (op != "1") bank.transact(id, op[0] - '0', amount, target);
                const auto& r = bank.get(id);
                std::cout << "Dear " << r.name << ", your balance is " << formatMoney(r.balance) << '\n';
            } catch (const std::exception& e) {
                if (!std::cin) throw;
                std::cout << "Warning: " << e.what() << '\n';
            }
            std::string again;
            do { again = input("1. Continue\n2. Quit\nPlease select: "); } while (again != "1" && again != "2");
            if (again == "2") break;
        }
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
