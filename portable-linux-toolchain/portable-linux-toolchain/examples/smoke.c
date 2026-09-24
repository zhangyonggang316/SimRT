#include <math.h>
#include <stdio.h>

int main(void)
{
    volatile double input = 2.0;
    const double result = sqrt(input);
    printf("portable C: sqrt(2)=%.9f\n", result);
    return (result > 1.4142135 && result < 1.4142136) ? 0 : 1;
}
