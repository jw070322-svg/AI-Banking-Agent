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
