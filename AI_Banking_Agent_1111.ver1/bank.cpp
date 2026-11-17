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
