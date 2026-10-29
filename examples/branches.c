int choose(int x) {
    if (x > 3) {
        return 1;
    } else {
        return 0;
    }
}
int main(void) {
    printf("%d\n", choose(5));
    printf("%d\n", choose(1));
    return 0;
}
