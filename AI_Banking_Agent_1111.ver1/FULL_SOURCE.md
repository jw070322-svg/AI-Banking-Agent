## account.h

#pragma once
#include <cstdint>
#include <string>
using Money = std::int64_t;
// Policy classes demonstrate inheritance without duplicating ledger data.
class Account {
public:
    virtual ~Account() = default;
    virtual Money withdrawalLimit() const { return 200000; }
    virtual Money transferLimit() const { return 1000000; }
    virtual Money fee(Money cents) const { return (cents + 50) / 100; }
};
class VipAccount final : public Account {
public:
    Money withdrawalLimit() const override { return 300000; }
    Money transferLimit() const override { return 2000000; }
    Money fee(Money cents) const override { return (cents + 100) / 200; }
};
struct Record { std::string id, name, password; Money balance; bool vip; };
Money parseMoney(const std::string& text);
std::string formatMoney(Money value);

## bank.h

#pragma once
#include "account.h"
#include <map>
#include <string>
class Bank {
    std::map<std::string, Record> records;
    std::string path;
    void save(const std::map<std::string, Record>& next);
public:
    explicit Bank(std::string file);
    const Record& get(const std::string& id) const;
    void transact(const std::string& id, int operation, Money amount,
                  const std::string& target = "");
};

## bank.cpp

#include "bank.h"
#include <fstream>
#include <sstream>
#include <iomanip>
#include <stdexcept>
#include <utility>
#include <windows.h>
namespace {
constexpr Money maxMoney = 9000000000000000LL;
bool digits(const std::string& s, std::size_t n) {
    return s.size() == n && s.find_first_not_of("0123456789") == std::string::npos;
}
}
Money parseMoney(const std::string& s) {
    auto dot = s.find('.');
    auto whole = s.substr(0, dot);
    auto fraction = dot == std::string::npos ? "" : s.substr(dot + 1);
    if (whole.empty() || whole.size() > 14 || !digits(whole, whole.size()) ||
        fraction.size() > 2 || (!fraction.empty() && !digits(fraction, fraction.size())) ||
        (dot != std::string::npos && fraction.empty()))
        throw std::runtime_error("Invalid amount; use digits with at most two decimals.");
    while (fraction.size() < 2) fraction += '0';
    Money result = std::stoll(whole) * 100 + std::stoll(fraction);
    if (result > maxMoney) throw std::runtime_error("Amount too large.");
    return result;
}
std::string formatMoney(Money v) {
    std::ostringstream s; s << v / 100 << '.' << std::setw(2) << std::setfill('0') << v % 100;
    return s.str();
}
Bank::Bank(std::string file) : path(std::move(file)) {
    std::ifstream f(path); std::string line;
    if (!std::getline(f, line) || line != "accountNo accountName password Balance VIP")
        throw std::runtime_error("Missing or invalid account header.");
    while (std::getline(f, line)) {
        if (line.empty()) continue;
        std::istringstream row(line); Record r; std::string money, flag, extra;
        if (!(row >> r.id >> r.name >> r.password >> money >> flag) || row >> extra ||
            !digits(r.id, 4) || !digits(r.password, 6) || (flag != "V" && flag != "N"))
            throw std::runtime_error("Invalid account row.");
        r.balance = parseMoney(money); r.vip = flag == "V";
        if (!records.emplace(r.id, r).second) throw std::runtime_error("Duplicate account.");
    }
    if (f.bad() || records.empty()) throw std::runtime_error("Unreadable or empty accounts.");
}
const Record& Bank::get(const std::string& id) const {
    auto it = records.find(id);
    if (it == records.end()) throw std::runtime_error("Invalid account number.");
    return it->second;
}
void Bank::save(const std::map<std::string, Record>& next) {
    auto tmp = path + ".tmp";
    std::ofstream f(tmp, std::ios::trunc);
    f << "accountNo accountName password Balance VIP\n";
    for (const auto& item : next) {
        const auto& r = item.second;
        f << r.id << ' ' << r.name << ' ' << r.password << ' ' << formatMoney(r.balance)
          << ' ' << (r.vip ? 'V' : 'N') << '\n';
    }
    f.flush(); if (!f) throw std::runtime_error("Save failed; original file retained.");
    f.close(); if (!f) throw std::runtime_error("Close failed; original file retained.");
    if (!MoveFileExA(tmp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("Atomic replace failed; original file retained.");
}
void Bank::transact(const std::string& id, int op, Money amount, const std::string& target) {
    if (amount <= 0) throw std::runtime_error("Amount must be positive.");
    auto next = records; auto& from = next.at(id);
    Account normal; VipAccount vip; const Account& policy = from.vip ? static_cast<const Account&>(vip) : normal;
    if (op == 2) {
        if (amount > maxMoney - from.balance) throw std::runtime_error("Balance overflow.");
        from.balance += amount;
    } else if (op == 3) {
        if (amount > policy.withdrawalLimit()) throw std::runtime_error("Withdrawal limit exceeded.");
        if (amount > from.balance) throw std::runtime_error("Insufficient balance.");
        from.balance -= amount;
    } else if (op == 4) {
        if (id == target || !next.count(target)) throw std::runtime_error("Invalid target account.");
        if (amount > policy.transferLimit()) throw std::runtime_error("Transfer limit exceeded.");
        Money debit = amount + policy.fee(amount);
        if (debit > from.balance) throw std::runtime_error("Insufficient balance including fee.");
        auto& to = next.at(target);
        if (amount > maxMoney - to.balance) throw std::runtime_error("Target balance overflow.");
        from.balance -= debit; to.balance += amount;
    } else throw std::runtime_error("Invalid operation.");
    save(next); records.swap(next);
}

## main.cpp

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
